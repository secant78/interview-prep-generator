#!/usr/bin/env python3
"""
Ingest generated markdown docs into Pinecone using integrated inference.
Pinecone embeds the text internally — no separate embedding API call needed.

Usage:
    python ingest.py                          # indexes all docs in ./output/
    python ingest.py --dir path/to/docs       # custom folder
    python ingest.py --clear                  # wipe index and re-ingest
"""

import argparse
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from pinecone import Pinecone

load_dotenv()

PINECONE_INDEX = "interview-prep"
EMBED_MODEL    = "multilingual-e5-large"
NAMESPACE      = "__default__"


def get_pinecone():
    key = os.getenv("PINECONE_API_KEY")
    if not key:
        print("[ERROR] PINECONE_API_KEY not set in .env")
        sys.exit(1)
    return Pinecone(api_key=key)


def ensure_index(pc: Pinecone):
    existing = [i.name for i in pc.list_indexes()]
    if PINECONE_INDEX not in existing:
        print(f"  Creating Pinecone index '{PINECONE_INDEX}' with integrated embedding...")
        pc.create_index_for_model(
            name=PINECONE_INDEX,
            cloud="aws",
            region="us-east-1",
            embed={
                "model": EMBED_MODEL,
                "field_map": {"text": "chunk_text"},
            },
        )
        print("  Index created.")
    return pc.Index(PINECONE_INDEX)


def parse_filename(path: Path) -> dict:
    """Extract date, company, doc_type from filename like 05-30-26_Comcast_story.md"""
    stem = path.stem
    parts = stem.split("_", 2)
    if len(parts) == 3:
        return {"date": parts[0], "company": parts[1], "doc_type": parts[2]}
    return {"date": "unknown", "company": "unknown", "doc_type": stem}


def chunk_markdown(text: str, source_meta: dict) -> list[dict]:
    """Split markdown into chunks by ## and ### headers."""
    chunks = []
    sections = re.split(r"\n(?=#{2,3} )", text)
    for section in sections:
        section = section.strip()
        if not section or len(section) < 50:
            continue
        first_line = section.splitlines()[0].strip()
        title = re.sub(r"^#+\s*", "", first_line)
        chunks.append({"text": section, "title": title, **source_meta})
    return chunks


def ingest_file(path: Path, index) -> int:
    text = path.read_text(encoding="utf-8")
    meta = parse_filename(path)
    chunks = chunk_markdown(text, meta)

    if not chunks:
        print(f"  No chunks found in {path.name}, skipping.")
        return 0

    records = [
        {
            "_id":        f"{path.stem}_chunk{i}",
            "chunk_text": chunk["text"][:2000],
            "title":      chunk["title"],
            "company":    chunk["company"],
            "doc_type":   chunk["doc_type"],
            "date":       chunk["date"],
            "source":     path.name,
        }
        for i, chunk in enumerate(chunks)
    ]

    # Upsert in batches of 100
    for i in range(0, len(records), 100):
        index.upsert_records(records=records[i:i+100], namespace=NAMESPACE)

    return len(records)


def main():
    parser = argparse.ArgumentParser(description="Ingest interview prep docs into Pinecone.")
    parser.add_argument("--dir", default="output", help="Folder containing markdown docs (default: ./output)")
    parser.add_argument("--clear", action="store_true", help="Delete all vectors in the index before ingesting")
    args = parser.parse_args()

    doc_dir = Path(args.dir)
    if not doc_dir.exists():
        print(f"[ERROR] Directory not found: {doc_dir}")
        sys.exit(1)

    md_files = list(doc_dir.glob("*.md"))
    if not md_files:
        print(f"[ERROR] No markdown files found in {doc_dir}")
        sys.exit(1)

    pc    = get_pinecone()
    index = ensure_index(pc)

    if args.clear:
        print("  Clearing existing vectors...")
        index.delete(delete_all=True, namespace=NAMESPACE)

    print(f"\nIngesting {len(md_files)} file(s) from {doc_dir.resolve()}\n")

    total = 0
    for path in sorted(md_files):
        print(f"  Processing {path.name}...")
        count = ingest_file(path, index)
        print(f"  -> {count} chunks indexed")
        total += count

    print(f"\nDone. {total} total chunks indexed into '{PINECONE_INDEX}'.")


if __name__ == "__main__":
    main()
