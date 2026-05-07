"""Parse 518 articles from support.avito.ru via internal JSON API.

Outputs:
  data/articles_raw.jsonl  — one raw article JSON per line.
  data/catalog_map.json    — {"categories": {id: name}, "sections": {id: name}}.

Usage: python scripts/parse_articles.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from tqdm.asyncio import tqdm_asyncio

BASE = "https://support.avito.ru"
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Origin": BASE,
    "Referer": f"{BASE}/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru,en;q=0.9",
}

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_PATH = DATA_DIR / "articles_raw.jsonl"
CATALOG_RAW_PATH = DATA_DIR / "catalog_raw.json"
CATALOG_MAP_PATH = DATA_DIR / "catalog_map.json"

ARTICLE_URL_PREFIX = "https://support.avito.ru"

CONCURRENCY = 8
TIMEOUT = 20.0
EXPECTED_TOTAL = 518


async def fetch_catalog(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    r = await client.post(f"{BASE}/api/1/getCatalog", json={})
    r.raise_for_status()
    payload = r.json()
    # API wraps the tree in {"result": [...]}.
    result = payload.get("result", payload)
    if not isinstance(result, list):
        raise RuntimeError(f"Unexpected getCatalog payload shape: {type(result).__name__}")
    return result


async def fetch_article(
    client: httpx.AsyncClient, sem: asyncio.Semaphore, article_id: int
) -> dict[str, Any]:
    async with sem:
        r = await client.post(f"{BASE}/api/1/article", json={"id": article_id})
        r.raise_for_status()
        payload = r.json()
        return payload.get("result", payload)


def build_catalog_map(catalog: list[dict[str, Any]]) -> dict[str, Any]:
    """Build category/section name maps and per-article hierarchy.

    Catalog is a flat list of nodes with parentId. typeId=1 = category,
    typeId=2 = section, typeId=4 = article. categoryId/sectionId fields on
    /api/1/article responses are unrelated to catalog ids — true hierarchy
    is via parentId in the catalog. Sections are optional: ~68 of 518
    articles hang directly off a category.
    """
    by_id = {n["id"]: n for n in catalog if "id" in n}

    categories: dict[str, str] = {}
    sections: dict[str, str] = {}
    for n in catalog:
        if n.get("typeId") == 1:
            categories[str(n["id"])] = n.get("title") or ""
        elif n.get("typeId") == 2:
            sections[str(n["id"])] = n.get("title") or ""

    articles: dict[str, dict[str, Any]] = {}
    for n in catalog:
        if n.get("typeId") != 4:
            continue
        parent = by_id.get(n.get("parentId"))
        category_id: int | None = None
        section_id: int | None = None
        if parent is not None:
            if parent.get("typeId") == 2:
                section_id = parent["id"]
                gp = by_id.get(parent.get("parentId"))
                if gp is not None and gp.get("typeId") == 1:
                    category_id = gp["id"]
            elif parent.get("typeId") == 1:
                category_id = parent["id"]
        articles[str(n["id"])] = {
            "url": (ARTICLE_URL_PREFIX + n["url"]) if n.get("url") else None,
            "title": n.get("title") or "",
            "category_id": category_id,
            "category": categories.get(str(category_id)) if category_id else None,
            "section_id": section_id,
            "section": sections.get(str(section_id)) if section_id else None,
        }

    return {"categories": categories, "sections": sections, "articles": articles}


def confirm_overwrite(path: Path, line_count: int) -> bool:
    print(
        f"\n{path} already exists with {line_count} lines (expected {EXPECTED_TOTAL}).",
        file=sys.stderr,
    )
    answer = input("Overwrite? [y/N]: ").strip().lower()
    return answer in {"y", "yes"}


def count_lines(path: Path) -> int:
    with path.open("rb") as f:
        return sum(1 for _ in f)


async def fetch_all(
    article_ids: list[int],
) -> tuple[list[dict[str, Any]], list[tuple[int, str]]]:
    """Fetch every article. Returns (results, errors)."""
    sem = asyncio.Semaphore(CONCURRENCY)
    results: list[dict[str, Any] | None] = [None] * len(article_ids)
    errors: list[tuple[int, str]] = []

    async with httpx.AsyncClient(headers=HEADERS, timeout=TIMEOUT, http2=False) as client:

        async def worker(idx: int, aid: int) -> None:
            try:
                results[idx] = await fetch_article(client, sem, aid)
            except Exception as exc:
                errors.append((aid, repr(exc)))

        coros = [worker(i, aid) for i, aid in enumerate(article_ids)]
        for completed_idx, _ in enumerate(
            await tqdm_asyncio.gather(*coros, desc="fetch", total=len(coros)),
            start=1,
        ):
            if completed_idx % 50 == 0:
                print(f"Fetched {completed_idx}/{len(article_ids)}")

    fetched = [r for r in results if r is not None]
    return fetched, errors


async def retry_failed(
    failed_ids: list[int],
) -> tuple[list[dict[str, Any]], list[tuple[int, str]]]:
    if not failed_ids:
        return [], []
    print(f"\nRetrying {len(failed_ids)} failed articles...")
    sem = asyncio.Semaphore(CONCURRENCY)
    fetched: list[dict[str, Any]] = []
    errors: list[tuple[int, str]] = []
    async with httpx.AsyncClient(headers=HEADERS, timeout=TIMEOUT) as client:
        for aid in failed_ids:
            try:
                fetched.append(await fetch_article(client, sem, aid))
            except Exception as exc:
                errors.append((aid, repr(exc)))
    return fetched, errors


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


async def sanity_check() -> None:
    """One probe request before the bulk run."""
    async with httpx.AsyncClient(headers=HEADERS, timeout=TIMEOUT) as client:
        r = await client.post(f"{BASE}/api/1/getCatalog", json={})
        print(f"Sanity check: getCatalog → {r.status_code}, body length {len(r.text)}")
        r.raise_for_status()


async def main(args: argparse.Namespace) -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Idempotency guard.
    if RAW_PATH.exists() and not args.force:
        existing = count_lines(RAW_PATH)
        if existing >= EXPECTED_TOTAL - 8 and not confirm_overwrite(RAW_PATH, existing):
            print("Skipped — keeping existing articles_raw.jsonl.")
            return 0

    if args.sanity_only:
        await sanity_check()
        return 0

    await sanity_check()

    started = time.perf_counter()

    print("Fetching catalog...")
    async with httpx.AsyncClient(headers=HEADERS, timeout=TIMEOUT) as client:
        catalog = await fetch_catalog(client)
    print(f"Catalog: {len(catalog)} nodes total")

    CATALOG_RAW_PATH.write_text(
        json.dumps(catalog, ensure_ascii=False), encoding="utf-8"
    )

    catalog_map = build_catalog_map(catalog)
    print(
        f"Catalog map: {len(catalog_map['categories'])} categories, "
        f"{len(catalog_map['sections'])} sections, "
        f"{len(catalog_map['articles'])} articles in hierarchy"
    )

    article_nodes = [n for n in catalog if n.get("typeId") == 4]
    article_ids = [int(n["id"]) for n in article_nodes]
    print(f"Articles (typeId=4): {len(article_ids)}")

    if len(article_ids) < EXPECTED_TOTAL - 20:
        print(
            f"WARNING: expected ~{EXPECTED_TOTAL} articles, got {len(article_ids)}.",
            file=sys.stderr,
        )

    # Bulk fetch.
    fetched, errors = await fetch_all(article_ids)

    # Retry failed once.
    if errors:
        retry_fetched, retry_errors = await retry_failed([aid for aid, _ in errors])
        fetched.extend(retry_fetched)
        errors = retry_errors

    # Edge case: article id missing in catalog hierarchy or url missing.
    article_meta = catalog_map["articles"]
    no_url: list[int] = []
    no_category: list[int] = []
    for art in fetched:
        aid = art.get("id")
        meta = article_meta.get(str(aid))
        if meta is None or not meta.get("url"):
            no_url.append(aid)
            print(f"WARN: article {aid} has no URL in catalog", file=sys.stderr)
        elif meta.get("category_id") is None:
            no_category.append(aid)
            print(f"WARN: article {aid} has no category in catalog", file=sys.stderr)

    write_jsonl(RAW_PATH, fetched)

    CATALOG_MAP_PATH.write_text(
        json.dumps(catalog_map, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    elapsed = time.perf_counter() - started
    print("\n=== Summary ===")
    print(f"Catalog nodes:     {len(catalog)}")
    print(f"Article ids:       {len(article_ids)}")
    print(f"Fetched OK:        {len(fetched)}")
    print(f"Errors (final):    {len(errors)}")
    print(f"Without URL:       {len(no_url)}")
    print(f"Without category:  {len(no_category)}")
    print(f"Elapsed:           {elapsed:.1f}s")
    print(f"Wrote: {RAW_PATH.relative_to(ROOT)}")
    print(f"Wrote: {CATALOG_RAW_PATH.relative_to(ROOT)}")
    print(f"Wrote: {CATALOG_MAP_PATH.relative_to(ROOT)}")
    if errors:
        for aid, msg in errors[:5]:
            print(f"  err {aid}: {msg}", file=sys.stderr)
    return 0 if not errors else 1


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Parse support.avito.ru articles via JSON API.")
    p.add_argument("--force", action="store_true", help="Overwrite existing files without asking.")
    p.add_argument("--sanity-only", action="store_true", help="Only run the probe request.")
    return p.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(parse_args())))
