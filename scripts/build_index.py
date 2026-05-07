"""Embed chunks via OpenAI and persist into Chroma.

Reads:
  data/articles.jsonl  — chunk records from build_chunks.py.

Writes:
  data/chroma/         — persistent Chroma store (path overridable via CHROMA_PATH).

Usage: python scripts/build_index.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import chromadb
import tiktoken
from dotenv import load_dotenv
from openai import OpenAI
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CHUNKS_PATH = DATA_DIR / "articles.jsonl"

DEFAULT_CHROMA_PATH = str(DATA_DIR / "chroma")
COLLECTION_NAME = "avi_help"

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536
EMBEDDING_PRICE_PER_1M_TOKENS = 0.02  # USD, text-embedding-3-small.
COST_HARD_STOP = 0.10  # USD — bail out if estimate exceeds this.

BATCH_SIZE = 100

ENCODER = tiktoken.get_encoding("cl100k_base")

SANITY_QUERIES = [
    "как вернуть деньги если продавец не отвечает",
    "как разместить объявление",
    "звонят с поддельной ссылкой",
]


def load_chunks(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def chunk_to_metadata(chunk: dict[str, Any]) -> dict[str, Any]:
    """Chroma metadata can't hold None values — coerce to defaults."""
    md: dict[str, Any] = {}
    for key in (
        "chunk_id",
        "article_id",
        "article_url",
        "title",
        "category",
        "section",
        "category_id",
        "section_id",
        "lastmod",
        "chunk_index",
        "total_chunks",
    ):
        v = chunk.get(key)
        if v is None:
            v = ""
        md[key] = v
    return md


def confirm_collection_action(existing_count: int) -> str:
    print(
        f"\nCollection {COLLECTION_NAME!r} already exists with {existing_count} records.",
        file=sys.stderr,
    )
    print("  [r]ecreate   — drop collection and rebuild from scratch", file=sys.stderr)
    print("  [u]pdate     — upsert all chunks (idempotent)", file=sys.stderr)
    print("  [s]kip       — leave as is and just run sanity check", file=sys.stderr)
    while True:
        choice = input("Choose [r/u/s]: ").strip().lower()
        if choice in {"r", "u", "s"}:
            return choice


def estimate_cost(chunks: list[dict[str, Any]]) -> tuple[int, float]:
    total_tokens = sum(len(ENCODER.encode(c["chunk_text"])) for c in chunks)
    cost = total_tokens / 1_000_000 * EMBEDDING_PRICE_PER_1M_TOKENS
    return total_tokens, cost


def embed_batch(client: OpenAI, texts: list[str]) -> list[list[float]]:
    resp = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    # Preserve order: OpenAI returns objects with .index that should match.
    by_index = {item.index: item.embedding for item in resp.data}
    return [by_index[i] for i in range(len(texts))]


def index_chunks(
    client: OpenAI,
    collection: chromadb.api.models.Collection.Collection,
    chunks: list[dict[str, Any]],
) -> int:
    """Embed and upsert all chunks. Returns total tokens actually consumed."""
    total_tokens = 0
    for start in tqdm(range(0, len(chunks), BATCH_SIZE), desc="embed", unit="batch"):
        batch = chunks[start : start + BATCH_SIZE]
        texts = [c["chunk_text"] for c in batch]

        # Token bookkeeping (pre-call so we can track even on retry).
        total_tokens += sum(len(ENCODER.encode(t)) for t in texts)

        embeddings = embed_batch(client, texts)

        collection.upsert(
            ids=[c["chunk_id"] for c in batch],
            embeddings=embeddings,
            documents=texts,
            metadatas=[chunk_to_metadata(c) for c in batch],
        )
    return total_tokens


def run_sanity_check(
    client: OpenAI,
    collection: chromadb.api.models.Collection.Collection,
) -> None:
    print("\n=== Sanity check: 3 test queries ===")
    for query in SANITY_QUERIES:
        emb = client.embeddings.create(model=EMBEDDING_MODEL, input=[query]).data[0].embedding
        res = collection.query(query_embeddings=[emb], n_results=3)
        print(f"\nQ: {query!r}")
        ids = res["ids"][0]
        docs = res["documents"][0]
        metas = res["metadatas"][0]
        # Chroma returns squared L2 distance by default; lower = more similar.
        dists = res["distances"][0] if res.get("distances") else [None] * len(ids)
        for rank, (cid, doc, meta, dist) in enumerate(zip(ids, docs, metas, dists), start=1):
            score_str = f"{dist:.4f}" if dist is not None else "n/a"
            preview = doc.replace("\n", " ")[:200]
            print(
                f"  [{rank}] id={cid} dist={score_str} | "
                f"title={meta.get('title')!r} category={meta.get('category')!r}"
            )
            print(f"      {preview}")


def main(args: argparse.Namespace) -> int:
    load_dotenv(ROOT / "backend" / ".env")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY not set. Add it to backend/.env.", file=sys.stderr)
        return 1

    if not CHUNKS_PATH.exists():
        print(f"Missing {CHUNKS_PATH}. Run build_chunks.py first.", file=sys.stderr)
        return 1

    chroma_path = Path(os.getenv("CHROMA_PATH", DEFAULT_CHROMA_PATH))
    chroma_path.mkdir(parents=True, exist_ok=True)
    print(f"Chroma path: {chroma_path}")

    chunks = load_chunks(CHUNKS_PATH)
    print(f"Loaded {len(chunks)} chunks from {CHUNKS_PATH.relative_to(ROOT)}")

    est_tokens, est_cost = estimate_cost(chunks)
    print(f"Estimated indexing cost: ${est_cost:.4f} ({est_tokens:,} tokens)")
    if est_cost > COST_HARD_STOP:
        print(
            f"Estimated cost ${est_cost:.4f} exceeds hard stop ${COST_HARD_STOP}. "
            "Re-check chunk volume before continuing.",
            file=sys.stderr,
        )
        return 2

    chroma_client = chromadb.PersistentClient(path=str(chroma_path))

    existing_collection = None
    for col in chroma_client.list_collections():
        if col.name == COLLECTION_NAME:
            existing_collection = col
            break

    do_index = True
    if existing_collection is not None:
        existing_count = existing_collection.count()
        if args.force_recreate:
            chroma_client.delete_collection(COLLECTION_NAME)
            existing_collection = None
            print(f"Recreated empty collection {COLLECTION_NAME!r}")
        elif args.update_only:
            collection = existing_collection
            print(f"Updating existing collection ({existing_count} → {len(chunks)})")
        elif args.sanity_only:
            do_index = False
            collection = existing_collection
        else:
            choice = confirm_collection_action(existing_count)
            if choice == "r":
                chroma_client.delete_collection(COLLECTION_NAME)
                existing_collection = None
            elif choice == "s":
                do_index = False
                collection = existing_collection
            # 'u' falls through with existing_collection set.
            if choice in {"u", "r"}:
                pass

    if existing_collection is None:
        collection = chroma_client.create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        print(f"Created collection {COLLECTION_NAME!r} (cosine).")
    else:
        collection = existing_collection

    started = time.perf_counter()
    actual_tokens = 0
    if do_index:
        client = OpenAI(api_key=api_key)
        actual_tokens = index_chunks(client, collection, chunks)
    elapsed = time.perf_counter() - started

    actual_cost = actual_tokens / 1_000_000 * EMBEDDING_PRICE_PER_1M_TOKENS

    print("\n=== Indexing summary ===")
    print(f"Chunks indexed:      {len(chunks) if do_index else 0}")
    print(f"Records in Chroma:   {collection.count()}")
    print(f"Tokens consumed:     {actual_tokens:,}")
    print(f"Indexing cost:       ${actual_cost:.4f} ({actual_tokens} tokens)")
    print(f"Elapsed:             {elapsed:.1f}s")

    # Sanity check uses one fresh OpenAI client.
    sanity_client = OpenAI(api_key=api_key)
    run_sanity_check(sanity_client, collection)
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Embed chunks and store in Chroma.")
    p.add_argument("--force-recreate", action="store_true", help="Drop existing collection without prompt.")
    p.add_argument("--update-only", action="store_true", help="Upsert into existing collection without prompt.")
    p.add_argument("--sanity-only", action="store_true", help="Skip indexing; only run sanity queries on existing collection.")
    return p.parse_args()


if __name__ == "__main__":
    raise SystemExit(main(parse_args()))
