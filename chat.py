#!/usr/bin/env python3
"""
Query your interview prep docs via RAG.

Usage:
    python chat.py                            # interactive chat loop
    python chat.py --company Comcast          # filter to one company
    python chat.py --doc_type mock_qa         # filter to one doc type
    python chat.py -q "How do I answer the ELK question?"  # single query
"""

import argparse
import os
import sys

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pinecone import Pinecone

load_dotenv()

PINECONE_INDEX = "interview-prep"
EMBEDDING_MODEL = "text-embedding-004"
CHAT_MODEL = "gemini-2.5-flash"
TOP_K = 5

SYSTEM_PROMPT = """You are an expert interview coach. You have access to a candidate's personalized interview preparation documents — their career stories, technical deep dives, mock Q&A answers, and company-specific narratives.

When answering questions:
- Be specific and direct. Reference the actual content from the retrieved documents.
- If the question is about how to answer an interview question, give the full answer the candidate should use.
- If the question is about a specific company or role, focus on that context.
- Keep answers concise but complete. Don't pad with generic advice.
- If the retrieved context doesn't cover the question, say so clearly."""


def get_clients():
    pinecone_key = os.getenv("PINECONE_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not pinecone_key:
        print("[ERROR] PINECONE_API_KEY not set in .env")
        sys.exit(1)
    if not gemini_key:
        print("[ERROR] GEMINI_API_KEY not set in .env")
        sys.exit(1)
    pc = Pinecone(api_key=pinecone_key)
    gemini = genai.Client(api_key=gemini_key)
    return pc.Index(PINECONE_INDEX), gemini


def embed_query(gemini: genai.Client, query: str) -> list[float]:
    result = gemini.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=query,
        config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
    )
    return result.embeddings[0].values


def retrieve(index, embedding: list[float], filters: dict) -> list[dict]:
    query_kwargs = {
        "vector": embedding,
        "top_k": TOP_K,
        "include_metadata": True,
    }
    if filters:
        query_kwargs["filter"] = {k: {"$eq": v} for k, v in filters.items()}

    results = index.query(**query_kwargs)
    return [m.metadata for m in results.matches]


def build_context(chunks: list[dict]) -> str:
    parts = []
    for i, chunk in enumerate(chunks, 1):
        source = f"[{chunk.get('doc_type', 'doc')} | {chunk.get('company', '')} | {chunk.get('title', '')}]"
        parts.append(f"--- Source {i}: {source} ---\n{chunk.get('text', '')}")
    return "\n\n".join(parts)


def answer(gemini: genai.Client, query: str, context: str) -> str:
    prompt = f"""Use the following interview prep documents to answer the question.

CONTEXT:
{context}

QUESTION:
{query}"""

    response = gemini.models.generate_content(
        model=CHAT_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.4,
        ),
    )
    return response.text


def run_query(index, gemini: genai.Client, query: str, filters: dict) -> str:
    embedding = embed_query(gemini, query)
    chunks = retrieve(index, embedding, filters)
    if not chunks:
        return "No relevant documents found. Make sure you've run ingest.py first."
    context = build_context(chunks)
    return answer(gemini, query, context)


def main():
    parser = argparse.ArgumentParser(description="Chat with your interview prep docs.")
    parser.add_argument("-q", "--query", help="Single question (non-interactive mode)")
    parser.add_argument("--company", help="Filter results to a specific company (e.g. Comcast)")
    parser.add_argument("--doc_type", help="Filter to a doc type: story, playbook, mock_qa, narratives, tools")
    args = parser.parse_args()

    index, gemini = get_clients()

    filters = {}
    if args.company:
        filters["company"] = args.company
    if args.doc_type:
        filters["doc_type"] = args.doc_type

    filter_label = ""
    if filters:
        filter_label = " | Filters: " + ", ".join(f"{k}={v}" for k, v in filters.items())

    if args.query:
        print(run_query(index, gemini, args.query, filters))
        return

    print(f"\nInterview Prep Chat{filter_label}")
    print("Ask anything about your prep docs. Type 'exit' to quit.\n")

    while True:
        try:
            query = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not query:
            continue
        if query.lower() in ("exit", "quit", "q"):
            print("Goodbye.")
            break

        print("\nAssistant: ", end="", flush=True)
        response = run_query(index, gemini, query, filters)
        print(response)
        print()


if __name__ == "__main__":
    main()
