"""
Mock interview logic: question generation, answer scoring, and mic transcription.
"""

import json
import os
import re
import tempfile

from google import genai
from google.genai import types

CHAT_MODEL = "gemini-2.5-flash"
NAMESPACE = "__default__"


def generate_questions(index, gemini: genai.Client, n_questions: int, company_filter: str = "") -> list[str]:
    """Generate interview questions via RAG from the candidate's prep docs."""
    query = "mock interview questions technical behavioral situational experience"
    search_kwargs = {
        "namespace": NAMESPACE,
        "inputs": {"text": query},
        "top_k": 8,
        "fields": ["chunk_text", "title", "company", "doc_type"],
    }
    if company_filter:
        search_kwargs["filter"] = {"company": {"$eq": company_filter}}

    results = index.search(**search_kwargs)
    hits = results.get("result", {}).get("hits", [])

    if not hits:
        return []

    context_parts = []
    for hit in hits:
        f = hit.get("fields", {})
        context_parts.append(
            f"[{f.get('doc_type', '')} | {f.get('company', '')}]\n{f.get('chunk_text', '')}"
        )
    context = "\n\n".join(context_parts)

    prompt = f"""Based on the interview prep documents below, generate exactly {n_questions} distinct interview questions a real interviewer would ask this candidate.

Mix question types: technical depth questions (about specific tools and systems they've used), behavioral/STAR questions, and scenario/architecture questions. Ground every question in the actual skills, tools, companies, and experiences mentioned in the documents.

Output ONLY a numbered list — one question per line, no preamble, no explanations:
1. [question]
2. [question]

INTERVIEW PREP DOCUMENTS:
{context}"""

    response = gemini.models.generate_content(
        model=CHAT_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.8),
    )

    questions = []
    for line in response.text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        cleaned = re.sub(r"^\d+[.)]\s*", "", line).strip()
        if cleaned and len(cleaned) > 15:
            questions.append(cleaned)

    return questions[:n_questions]


def score_answer(
    index,
    gemini: genai.Client,
    question: str,
    answer: str,
    company_filter: str = "",
) -> dict:
    """Score a candidate's spoken answer against their prep material using RAG."""
    search_kwargs = {
        "namespace": NAMESPACE,
        "inputs": {"text": question},
        "top_k": 5,
        "fields": ["chunk_text", "title", "company", "doc_type"],
    }
    if company_filter:
        search_kwargs["filter"] = {"company": {"$eq": company_filter}}

    results = index.search(**search_kwargs)
    hits = results.get("result", {}).get("hits", [])

    context_parts = []
    for hit in hits:
        f = hit.get("fields", {})
        context_parts.append(
            f"[{f.get('doc_type', '')} | {f.get('company', '')}]\n{f.get('chunk_text', '')}"
        )
    context = "\n\n".join(context_parts) if context_parts else "No specific context retrieved."

    prompt = f"""You are an expert interview coach scoring a candidate's live interview answer.

QUESTION ASKED: {question}

CANDIDATE'S ANSWER: {answer}

RELEVANT PREP MATERIAL (ideal answer elements from the candidate's own prep documents):
{context}

Score the answer and return a JSON object with EXACTLY these fields:
{{
  "score": <integer 1-10>,
  "verdict": "<one concise sentence overall assessment>",
  "strengths": ["<specific strength from their actual words>", ...],
  "improvements": ["<specific actionable improvement>", ...],
  "missed_points": ["<key point from prep docs they didn't mention>", ...],
  "model_snippet": "<2-3 sentences showing how to strengthen the weakest part of their answer>"
}}

Be brutally specific — reference exact things they said or didn't say. Return ONLY the JSON object, no markdown, no extra text."""

    response = gemini.models.generate_content(
        model=CHAT_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.2),
    )

    text = response.text.strip()
    if "```" in text:
        text = re.sub(r"```(?:json)?\s*", "", text).replace("```", "").strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "score": 5,
            "verdict": "Score unavailable — see raw feedback below.",
            "strengths": [],
            "improvements": [text[:400]],
            "missed_points": [],
            "model_snippet": "",
        }


def transcribe_mic_audio(audio_bytes: bytes, mime_type: str = "audio/webm") -> str:
    """
    Transcribe mic recording bytes using Groq Whisper.
    Returns empty string if GROQ_API_KEY is not set.
    """
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if not groq_key:
        return ""

    from groq import Groq
    client = Groq(api_key=groq_key)

    ext_map = {
        "audio/webm": ".webm",
        "audio/ogg":  ".ogg",
        "audio/wav":  ".wav",
        "audio/mp4":  ".mp4",
        "audio/mpeg": ".mp3",
        "audio/x-m4a": ".m4a",
    }
    ext = ext_map.get(mime_type, ".webm")

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name

    try:
        with open(tmp_path, "rb") as f:
            result = client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=f,
                response_format="text",
            )
        return result if isinstance(result, str) else getattr(result, "text", str(result))
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
