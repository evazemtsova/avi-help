"""Slice 518 raw articles into ~5200 chunks for the RAG index.

Reads:
  data/articles_raw.jsonl  — raw article JSONs from parse_articles.py
  data/catalog_map.json    — article hierarchy (category, section, url)

Writes:
  data/articles.jsonl      — one chunk per line, with metadata.

Chunking strategy (per Sprint 1 brief):
  - <headline> tags split the article into sections.
  - <div class="spoiler"> is rendered inline as `[Раскрывающийся блок: <title>]\\n<content>`.
  - <div class="factoid"> is rendered inline as `[Важно: <content>]`.
  - <div class="tabset"> — each tab becomes a separate chunk with prefix
    `[Вкладка: <name>]`.
  - Target ~250 tokens per chunk (cl100k_base). <100 tokens → merge with neighbour.
    >400 tokens → split by paragraphs.

Usage: python scripts/build_chunks.py
"""

from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import sys
from pathlib import Path
from typing import Any, Iterator

import tiktoken
from bs4 import BeautifulSoup, NavigableString, Tag

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_PATH = DATA_DIR / "articles_raw.jsonl"
CATALOG_MAP_PATH = DATA_DIR / "catalog_map.json"
OUT_PATH = DATA_DIR / "articles.jsonl"

ENCODER = tiktoken.get_encoding("cl100k_base")

TARGET_TOKENS = 250
MAX_TOKENS = 400
MIN_TOKENS = 100
MAX_CHUNKS_PER_ARTICLE = 50


def count_tokens(text: str) -> int:
    return len(ENCODER.encode(text))


# ---------------------------------------------------------------------------
# HTML → block sequence
# ---------------------------------------------------------------------------

def render_paragraphs(node: Tag | NavigableString) -> str:
    """Render a node to plain text, preserving paragraph and list breaks."""
    if isinstance(node, NavigableString):
        return str(node).strip()

    parts: list[str] = []
    for child in node.children:
        if isinstance(child, NavigableString):
            text = str(child).strip()
            if text:
                parts.append(text)
            continue
        if not isinstance(child, Tag):
            continue
        name = child.name
        if name in {"p", "div", "section", "article"}:
            parts.append(render_paragraphs(child))
        elif name in {"ul", "ol"}:
            for li in child.find_all("li", recursive=False):
                item = li.get_text(separator=" ", strip=True)
                if item:
                    parts.append(f"- {item}")
        elif name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            heading = child.get_text(separator=" ", strip=True)
            if heading:
                parts.append(heading)
        elif name == "br":
            continue
        elif name == "img":
            continue
        elif name in {"strong", "em", "b", "i", "a", "span", "u", "code"}:
            text = child.get_text(separator=" ", strip=True)
            if text:
                parts.append(text)
        elif name == "table":
            for row in child.find_all("tr"):
                cells = [c.get_text(separator=" ", strip=True) for c in row.find_all(["td", "th"])]
                cells = [c for c in cells if c]
                if cells:
                    parts.append(" | ".join(cells))
        else:
            text = child.get_text(separator=" ", strip=True)
            if text:
                parts.append(text)

    return "\n".join(p for p in parts if p)


def render_spoiler(spoiler: Tag) -> str:
    title_el = spoiler.select_one(".spoiler-title")
    content_el = spoiler.select_one(".spoiler-content")
    title = title_el.get_text(separator=" ", strip=True) if title_el else ""
    content = render_paragraphs(content_el) if content_el else ""
    body = f"[Раскрывающийся блок: {title}]"
    return f"{body}\n{content}" if content else body


def render_factoid(factoid: Tag) -> str:
    text = factoid.get_text(separator=" ", strip=True)
    return f"[Важно: {text}]"


def split_tabset(tabset: Tag) -> list[tuple[str, str]]:
    """Return [(label, panel_text)] for each tab in the tabset."""
    labels = [
        l.get_text(separator=" ", strip=True)
        for l in tabset.select("label.tab-label")
    ]
    panels = tabset.select("div.tab-panel")
    out: list[tuple[str, str]] = []
    for i, panel in enumerate(panels):
        label = labels[i] if i < len(labels) else f"вкладка {i + 1}"
        text = render_paragraphs(panel)
        if text:
            out.append((label, text))
    return out


def headline_text(headline: Tag) -> str:
    name_attr = headline.get("name")
    if name_attr:
        return str(name_attr).strip()
    return headline.get_text(separator=" ", strip=True)


def walk_blocks(body: Tag) -> Iterator[dict[str, Any]]:
    """Walk top-level children of <body>, yielding typed blocks.

    Block kinds:
      - {"kind": "header", "text": "..."}        → starts new section
      - {"kind": "tab", "label": "...", "text": "..."} → standalone chunk
      - {"kind": "text", "text": "..."}          → goes into current section
    """
    for child in body.children:
        if isinstance(child, NavigableString):
            text = str(child).strip()
            if text:
                yield {"kind": "text", "text": text}
            continue
        if not isinstance(child, Tag):
            continue

        name = child.name
        classes = set(child.get("class") or [])

        if name == "headline":
            yield {"kind": "header", "text": headline_text(child)}
        elif name in {"h1", "h2", "h3"}:
            text = child.get_text(separator=" ", strip=True)
            if text:
                yield {"kind": "header", "text": text}
        elif "tabset" in classes:
            for label, text in split_tabset(child):
                yield {"kind": "tab", "label": label, "text": text}
        elif "spoiler" in classes:
            yield {"kind": "text", "text": render_spoiler(child)}
        elif "factoid" in classes:
            yield {"kind": "text", "text": render_factoid(child)}
        else:
            text = render_paragraphs(child)
            if text:
                yield {"kind": "text", "text": text}


# ---------------------------------------------------------------------------
# Block sequence → chunk texts
# ---------------------------------------------------------------------------

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")


def hard_split_by_tokens(text: str) -> list[str]:
    """Last-resort split for content with no sentence/paragraph structure
    (flat tables, comma-only lists). Splits at TARGET_TOKENS boundaries."""
    tokens = ENCODER.encode(text)
    if len(tokens) <= MAX_TOKENS:
        return [text]
    return [
        ENCODER.decode(tokens[i : i + TARGET_TOKENS])
        for i in range(0, len(tokens), TARGET_TOKENS)
    ]


def split_paragraph_by_sentences(paragraph: str) -> list[str]:
    """Group sentences of a too-long paragraph into ~target-sized chunks.

    Used when a single rendered paragraph already exceeds MAX_TOKENS (long
    inline tables, comma-separated lists, etc.). Falls through to hard token
    split for paragraphs with no sentence boundaries.
    """
    if count_tokens(paragraph) <= MAX_TOKENS:
        return [paragraph]
    sentences = [s for s in SENTENCE_SPLIT_RE.split(paragraph.strip()) if s]
    if len(sentences) <= 1:
        return hard_split_by_tokens(paragraph)
    chunks: list[str] = []
    buf: list[str] = []
    buf_tokens = 0
    for s in sentences:
        st = count_tokens(s)
        if buf and buf_tokens + st > MAX_TOKENS:
            chunks.append(" ".join(buf))
            buf = [s]
            buf_tokens = st
        else:
            buf.append(s)
            buf_tokens += st
    if buf:
        chunks.append(" ".join(buf))
    # Final pass: any single sentence still too long → hard split.
    final: list[str] = []
    for c in chunks:
        final.extend(hard_split_by_tokens(c))
    return final


def split_section_by_paragraphs(text: str) -> list[str]:
    """Split a too-long section into ~target-sized paragraph groups.

    Tries to keep a list (`-` lines) together. If a single paragraph already
    exceeds MAX_TOKENS, fall through to sentence-level split first.
    """
    raw_paragraphs = [p for p in text.split("\n") if p.strip()]
    paragraphs: list[str] = []
    for p in raw_paragraphs:
        paragraphs.extend(split_paragraph_by_sentences(p))

    chunks: list[str] = []
    buf: list[str] = []
    buf_tokens = 0

    def flush() -> None:
        nonlocal buf, buf_tokens
        if buf:
            chunks.append("\n".join(buf))
            buf = []
            buf_tokens = 0

    for para in paragraphs:
        ptokens = count_tokens(para)
        if buf and buf_tokens + ptokens > MAX_TOKENS:
            flush()
        buf.append(para)
        buf_tokens += ptokens
        if buf_tokens >= TARGET_TOKENS and not para.startswith("- "):
            # Avoid breaking in the middle of a list.
            flush()

    flush()
    return chunks


def merge_small(chunks: list[str]) -> list[str]:
    """Merge chunks <MIN_TOKENS with the next chunk (or previous if last)."""
    if not chunks:
        return chunks
    merged: list[str] = []
    i = 0
    while i < len(chunks):
        cur = chunks[i]
        if count_tokens(cur) < MIN_TOKENS and i + 1 < len(chunks):
            cur = cur + "\n" + chunks[i + 1]
            i += 2
        else:
            i += 1
        merged.append(cur)
    # If the very last chunk is small, fold it into the previous one.
    if len(merged) >= 2 and count_tokens(merged[-1]) < MIN_TOKENS:
        merged[-2] = merged[-2] + "\n" + merged[-1]
        merged.pop()
    return merged


def split_with_prefix(body: str, prefix_lines: list[str]) -> list[str]:
    """Split body by paragraphs into MAX_TOKENS-sized chunks, repeating prefix lines."""
    prefix = "\n".join(p for p in prefix_lines if p)
    parts = split_section_by_paragraphs(body)
    if not prefix:
        return parts
    return [f"{prefix}\n{p}" for p in parts]


def section_to_chunks(
    title: str, header: str | None, paragraphs: list[str]
) -> list[str]:
    """Build chunk texts for one section. Article title and header prefix every chunk."""
    body = "\n".join(p for p in paragraphs if p.strip())
    if not body.strip():
        return []
    prefix_lines = [title] + ([header] if header else [])
    full = "\n".join(prefix_lines + [body])
    if count_tokens(full) <= MAX_TOKENS:
        return [full]
    return split_with_prefix(body, prefix_lines)


def tab_to_chunks(title: str, label: str, body: str) -> list[str]:
    prefix_lines = [title, f"[Вкладка: {label}]"]
    full = "\n".join(prefix_lines + [body])
    if count_tokens(full) <= MAX_TOKENS:
        return [full]
    return split_with_prefix(body, prefix_lines)


def chunk_article_body(title: str, body_html: str) -> tuple[list[str], list[str]]:
    """Return (section_chunks, tab_chunks) for one article body."""
    soup = BeautifulSoup(body_html, "lxml")
    root = soup.body or soup

    blocks = list(walk_blocks(root))

    section_chunks: list[str] = []
    tab_chunks: list[str] = []

    current_header: str | None = None
    current_paragraphs: list[str] = []

    def flush_section() -> None:
        nonlocal current_paragraphs
        if current_paragraphs:
            section_chunks.extend(section_to_chunks(title, current_header, current_paragraphs))
            current_paragraphs = []

    for blk in blocks:
        kind = blk["kind"]
        if kind == "header":
            flush_section()
            current_header = blk["text"]
        elif kind == "tab":
            tab_chunks.extend(tab_to_chunks(title, blk["label"], blk["text"]))
        elif kind == "text":
            current_paragraphs.append(blk["text"])

    flush_section()

    section_chunks = merge_small(section_chunks)
    return section_chunks, tab_chunks


# ---------------------------------------------------------------------------
# Article → chunk records
# ---------------------------------------------------------------------------

def build_chunks_for_article(
    article: dict[str, Any], meta: dict[str, Any] | None
) -> tuple[list[dict[str, Any]], int]:
    """Return (chunk records, original count before cap)."""
    aid = article.get("id")
    title = article.get("title") or ""

    if meta is None or not meta.get("url"):
        print(f"WARN: article {aid} has no URL in catalog — skipping all chunks", file=sys.stderr)
        return [], 0

    section_chunks, tab_chunks = chunk_article_body(title, article.get("body") or "")
    texts = section_chunks + tab_chunks
    if not texts:
        print(f"WARN: article {aid} produced 0 chunks (empty body?)", file=sys.stderr)
        return [], 0

    original_count = len(texts)
    if original_count > MAX_CHUNKS_PER_ARTICLE:
        texts = texts[:MAX_CHUNKS_PER_ARTICLE]

    total = len(texts)
    out: list[dict[str, Any]] = []
    for idx, text in enumerate(texts):
        out.append(
            {
                "chunk_id": f"{aid}_{idx:03d}",
                "article_id": aid,
                "article_url": meta["url"],
                "title": title,
                "category": meta.get("category"),
                "section": meta.get("section"),
                "category_id": meta.get("category_id"),
                "section_id": meta.get("section_id"),
                "lastmod": None,
                "chunk_text": text,
                "chunk_index": idx,
                "total_chunks": total,
            }
        )
    return out, original_count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_articles(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def main(args: argparse.Namespace) -> int:
    if not RAW_PATH.exists():
        print(f"Missing {RAW_PATH}", file=sys.stderr)
        return 1
    if not CATALOG_MAP_PATH.exists():
        print(f"Missing {CATALOG_MAP_PATH}", file=sys.stderr)
        return 1

    catalog_map = json.loads(CATALOG_MAP_PATH.read_text(encoding="utf-8"))
    articles_meta: dict[str, Any] = catalog_map["articles"]

    all_chunks: list[dict[str, Any]] = []
    n_articles = 0
    n_skipped = 0
    n_no_section = 0
    chunks_per_article: list[int] = []
    capped: list[tuple[int, int]] = []  # (article_id, original_count)

    for article in load_articles(RAW_PATH):
        n_articles += 1
        meta = articles_meta.get(str(article["id"]))
        chunks, original_count = build_chunks_for_article(article, meta)
        if not chunks:
            n_skipped += 1
            continue
        if original_count > MAX_CHUNKS_PER_ARTICLE:
            capped.append((article["id"], original_count))
        if meta and meta.get("section") is None:
            n_no_section += 1
        chunks_per_article.append(len(chunks))
        all_chunks.extend(chunks)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        for c in all_chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    # Stats
    sizes = [count_tokens(c["chunk_text"]) for c in all_chunks]
    sizes_sorted = sorted(sizes)

    def pct(p: float) -> int:
        if not sizes_sorted:
            return 0
        idx = max(0, min(len(sizes_sorted) - 1, int(round(p / 100 * (len(sizes_sorted) - 1)))))
        return sizes_sorted[idx]

    unique_articles = len({c["article_id"] for c in all_chunks})
    no_category = sum(1 for c in all_chunks if c["category"] is None)
    no_section = sum(1 for c in all_chunks if c["section"] is None)

    print("\n=== Chunking summary ===")
    print(f"Articles read:         {n_articles}")
    print(f"Articles skipped:      {n_skipped}")
    print(f"Articles with chunks:  {unique_articles}")
    print(f"Articles w/o section:  {n_no_section}  (chunks inherit None for section)")
    print(f"Total chunks:          {len(all_chunks)}")
    if chunks_per_article:
        print(
            f"Chunks per article:    "
            f"min={min(chunks_per_article)} "
            f"avg={sum(chunks_per_article) / len(chunks_per_article):.1f} "
            f"median={statistics.median(chunks_per_article):.0f} "
            f"max={max(chunks_per_article)}"
        )
    if sizes:
        print(
            f"Token sizes:           "
            f"min={min(sizes)} P50={pct(50)} P90={pct(90)} P95={pct(95)} P99={pct(99)} max={max(sizes)}"
        )
        print(f"Mean tokens:           {sum(sizes) / len(sizes):.1f}")
    print(f"Chunks w/o category:   {no_category}")
    print(f"Chunks w/o section:    {no_section}")
    if capped:
        capped_summary = ", ".join(f"{aid} ({cnt}→{MAX_CHUNKS_PER_ARTICLE})" for aid, cnt in capped)
        print(f"Capped articles:       {len(capped)} (article_ids: {capped_summary})")
    else:
        print(f"Capped articles:       0")
    print(f"\nWrote: {OUT_PATH.relative_to(ROOT)}")

    if args.show_samples:
        print("\n=== 5 random chunks ===")
        rng = random.Random(args.seed)
        for c in rng.sample(all_chunks, k=min(5, len(all_chunks))):
            print(
                f"\n--- chunk {c['chunk_id']} | "
                f"{c['title']!r} | category={c['category']!r} section={c['section']!r} | "
                f"{count_tokens(c['chunk_text'])} tokens ---"
            )
            print(c["chunk_text"])

    if len(all_chunks) < 3000 or len(all_chunks) > 8000:
        print(
            f"\nWARNING: chunk count {len(all_chunks)} outside expected 3000–8000 band.",
            file=sys.stderr,
        )
        return 2

    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build RAG chunks from raw articles.")
    p.add_argument("--show-samples", action="store_true", help="Print 5 random chunks at the end.")
    p.add_argument("--seed", type=int, default=42, help="Random seed for sample selection.")
    return p.parse_args()


if __name__ == "__main__":
    raise SystemExit(main(parse_args()))
