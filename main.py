#!/usr/bin/env python3
"""
Interview Prep Generator
Generates 5 interview prep documents from a resume + job description.

Usage:
    python main.py --resume resume.txt --job job.txt --company Comcast --role "DevOps Engineer"
    python main.py --resume resume.pdf --job job.txt --company Google --role "SRE"
    python main.py --resume resume.txt --job job.txt --all
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from google import genai
from dotenv import load_dotenv

from generators import (
    generate_story,
    generate_playbook,
    generate_mock_qa,
    generate_narratives,
    generate_tools,
)

load_dotenv()

DOCS = {
    "story":      ("story",      "The Complete Story (Faceless Man narrative)"),
    "playbook":   ("playbook",   "Interview Prep Playbook (gap analysis + STAR stories)"),
    "mock_qa":    ("mock_qa",    "Mock Interview Q&A (15 questions + scoring rubric)"),
    "narratives": ("narratives", "Profile Narratives (STAR per company)"),
    "tools":      ("tools",      "Tools Narratives (per-tool answers)"),
}

GENERATORS = {
    "story":      generate_story,
    "playbook":   generate_playbook,
    "mock_qa":    generate_mock_qa,
    "narratives": generate_narratives,
    "tools":      generate_tools,
}


def read_resume(path: str) -> str:
    p = Path(path)
    if not p.exists():
        print(f"[ERROR] Resume file not found: {path}")
        sys.exit(1)

    if p.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            print("[ERROR] pypdf is required to read PDFs. Run: pip install pypdf")
            sys.exit(1)
        reader = PdfReader(str(p))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    return p.read_text(encoding="utf-8")


def read_job(path: str) -> str:
    p = Path(path)
    if not p.exists():
        print(f"[ERROR] Job description file not found: {path}")
        sys.exit(1)
    return p.read_text(encoding="utf-8")


def slugify(text: str) -> str:
    return text.replace(" ", "_").replace("/", "-")


def generate_and_save(
    client: genai.Client,
    doc_key: str,
    resume: str,
    job_desc: str,
    output_dir: Path,
    company: str,
    role: str,
) -> Path:
    _, label = DOCS[doc_key]
    generator = GENERATORS[doc_key]

    date_str = datetime.now().strftime("%m-%d-%y")
    company_slug = slugify(company)
    filename = f"{date_str}_{company_slug}_{doc_key}.md"
    out_path = output_dir / filename

    print(f"  Generating {label}...")
    content = generator(client, resume, job_desc)

    # Prepend a metadata header
    header = f"<!-- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | Company: {company} | Role: {role} -->\n\n"
    out_path.write_text(header + content, encoding="utf-8")
    print(f"  Saved → {out_path}")
    return out_path


def main():
    parser = argparse.ArgumentParser(
        description="Generate interview prep documents from a resume and job description."
    )
    parser.add_argument("--resume", required=True, help="Path to resume (.txt or .pdf)")
    parser.add_argument("--job", required=True, help="Path to job description (.txt)")
    parser.add_argument("--company", required=True, help="Target company name")
    parser.add_argument("--role", required=True, help="Target role title")
    parser.add_argument(
        "--out",
        default="output",
        help="Output directory (default: ./output)",
    )
    parser.add_argument(
        "--docs",
        nargs="+",
        choices=list(DOCS.keys()) + ["all"],
        default=["all"],
        help=(
            "Which documents to generate. Options: "
            + ", ".join(DOCS.keys())
            + ", all (default: all)"
        ),
    )

    args = parser.parse_args()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("[ERROR] GEMINI_API_KEY not set. Add it to .env or export it.")
        print("       Get a free key at: https://aistudio.google.com/apikey")
        sys.exit(1)

    resume = read_resume(args.resume)
    job_desc = read_job(args.job)

    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)

    doc_keys = list(DOCS.keys()) if "all" in args.docs else args.docs

    client = genai.Client(api_key=api_key)

    print(f"\nInterview Prep Generator")
    print(f"  Company : {args.company}")
    print(f"  Role    : {args.role}")
    print(f"  Docs    : {', '.join(doc_keys)}")
    print(f"  Output  : {output_dir.resolve()}\n")

    generated = []
    for key in doc_keys:
        try:
            path = generate_and_save(
                client, key, resume, job_desc, output_dir, args.company, args.role
            )
            generated.append(path)
        except Exception as e:
            print(f"  [ERROR] Failed to generate {key}: {e}")

    print(f"\nDone. {len(generated)}/{len(doc_keys)} documents generated.")
    for p in generated:
        print(f"  {p}")


if __name__ == "__main__":
    main()
