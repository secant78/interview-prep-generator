#!/usr/bin/env python3
"""
Ingest generated markdown docs into Pinecone.

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
from google import genai
from google.genai import types
from pinecone import Pinecone, ServerlessSpec

load_dotenv()

PINECONE_INDEX = "interview-prep"
EMBEDDING_MODEL = "text-embedding-004"
EMBEDDING_DIM = 768


def get_clients():
    pinecone_key = os.getenv("PINECONE_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not pinecone_key:
        print("[ERROR] PINECONE_API_KEY not set in .env")
        sys.exit(1)
    if not gemini_key:
        print("[ERROR] GEMINI_API_KEY not set in .env")
        sys.exit(1)
    return Pinecone(api_key=pinecone_key), genai.Client(api_key=gemini_key)


def ensure_index(pc: Pinecone):
    existing = [i.name for i in pc.list_indexes()]
    if PINECONE_INDEX not in existing:
        print(f"  Creating Pinecone index '{PINECONE_INDEX}'...")
        pc.create_index(
            name=PINECONE_INDEX,
            dimension=EMBEDDING_DIM,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
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
    """Split markdown into chunks by ## and ### headers, preserving context."""
    chunks = []
    # Split on h2/h3 headers
    sections = re.split(r"\n(?=#{2,3} )", text)
    for section in sections:
        section = section.strip()
        if not section or len(section) < 50:
            continue
        # Extract header as title
        first_line = section.splitlines()[0].strip()
        title = re.sub(r"^#+\s*", "", first_line)
        chunks.append({
            "text": section,
            "title": title,
            **source_meta,
        })
    return chunks


def embed_texts(gemini: genai.Client, texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts using Google text-embedding-004."""
    result = gemini.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=texts,
        config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
    )
    return [e.values for e in result.embeddings]


def ingest_file(path: Path, index, gemini: genai.Client) -> int:
    text = path.read_text(encoding="utf-8")
    meta = parse_filename(path)
    chunks = chunk_markdown(text, meta)

    if not chunks:
        print(f"  No chunks found in {path.name}, skipping.")
        return 0

    texts = [c["text"] for c in chunks]
    embeddings = embed_texts(gemini, texts)

    vectors = []
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        vector_id = f"{path.stem}_chunk{i}"
        vectors.append({
            "id": vector_id,
            "values": embedding,
            "metadata": {
                "text": chunk["text"][:2000],  # Pinecone metadata limit
                "title": chunk["title"],
                "company": chunk["company"],
                "doc_type": chunk["doc_type"],
                "date": chunk["date"],
                "source": path.name,
            },
        })

    # Upsert in batches of 100
    for i in range(0, len(vectors), 100):
        index.upsert(vectors=vectors[i:i+100])

    return len(vectors)


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

    pc, gemini = get_clients()
    index = ensure_index(pc)

    if args.clear:
        print("  Clearing existing vectors...")
        index.delete(delete_all=True)

    print(f"\nIngesting {len(md_files)} file(s) from {doc_dir.resolve()}\n")

    total = 0
    for path in sorted(md_files):
        print(f"  Processing {path.name}...")
        count = ingest_file(path, index, gemini)
        print(f"  → {count} chunks indexed")
        total += count

    print(f"\nDone. {total} total chunks indexed into '{PINECONE_INDEX}'.")


if __name__ == "__main__":
    main()
