"""
Interview Video Analyzer
- Call 1 (video): transcript + visual analysis (eye contact, body language, posture, gestures, expressions)
- Call 2 (text only): feed transcript to analyze filler words, answer quality, STAR method, coding question
- Combine both into one final report
"""

import time
from datetime import datetime

from google import genai
from google.genai import types

SUPPORTED_MIME = {
    "mp4":  "video/mp4",
    "mov":  "video/quicktime",
    "avi":  "video/x-msvideo",
    "mkv":  "video/x-matroska",
    "webm": "video/webm",
    "flv":  "video/x-flv",
    "mpeg": "video/mpeg",
    "mpg":  "video/mpeg",
}

# ── Call 1: Video prompt ──────────────────────────────────────────────────────
# Covers everything that requires actually watching the video:
# transcript + visual analysis only.

VIDEO_PROMPT_TEMPLATE = """\
You are an expert interview coach watching a recorded interview video.

Your job has two parts. Produce both in a single response.

SPEAKER NAMES:
- Interviewee (candidate): {interviewee_name}
- Interviewer: {interviewer_name}

Use these exact names throughout the entire transcript. Do NOT use generic labels like "Candidate", "Speaker 1", or "Speaker 2".

---

## PART 1 — FULL TRANSCRIPT

Transcribe every word spoken by all participants.

Format:

# Interview Transcript

## Speakers
- **{interviewee_name}** — Candidate / Interviewee
- **{interviewer_name}** — Interviewer

---

[HH:MM:SS] **{interviewee_name}**: Exact words spoken here.

Rules:
- Timestamp every new speaker turn AND every ~30 seconds within a long continuous speech.
- Transcribe exactly — do not paraphrase. Include filler words (um, uh, like, you know).
- Mark inaudible sections as [inaudible]. Mark long silences as [pause ~Xs].
- Always use {interviewee_name} and {interviewer_name} — never substitute with generic labels.

---

## PART 2 — VISUAL ANALYSIS

Analyze ONLY what can be observed by watching the video (not the words spoken).
Do NOT comment on speech content, filler words, or answer quality — that will be done separately.

Detect the company from visual cues (logos, screen content, email domains, interviewer intro).

Produce this section in Markdown:

# Visual Analysis

**Company:** [detected company name, or "Unknown"]
**Interview type:** [Behavioral / Technical / Coding / General]

### Body Language & Posture
**Score: X/10**
- Posture: [upright / slouched / mixed — with timestamps for notable moments]
- Hand gestures: [purposeful / distracting / absent — with timestamps]
- Fidgeting / nervous habits: [describe specific behaviors with timestamps]
- Head nodding and active listening signals
- Overall physical presence

### Eye Contact
**Score: X/10**
- Consistency with camera/interviewer
- Pattern of looking away (thinking vs nerves vs reading notes)
- Notable timestamps where eye contact was strong or weak

### Facial Expressions
**Score: X/10**
- Genuine vs forced smiles
- Signs of nervousness or discomfort with timestamps
- Expressiveness and engagement level
- Resting expression during listening

### Overall Visual Presence
**Score: X/10**
- First impression from body language alone
- Confidence signals
- Professional appearance
""".strip()


# ── Call 2: Text-only prompt ──────────────────────────────────────────────────
# Fed the transcript as plain text. No video tokens consumed.

TEXT_PROMPT_TEMPLATE = """\
You are an expert interview coach. Below is a full timestamped transcript of a recorded interview.

Analyze the transcript and produce a detailed text-based feedback report in Markdown.
Focus ONLY on what can be evaluated from the words — do not comment on visuals.

---

## WHAT TO ANALYZE

### 1. Speech Patterns
- Filler words: count every "um", "uh", "like", "you know", "so", "basically", "literally".
  Give a total count and frequency (per minute estimate).
- Speaking pace: estimated words per minute based on timestamps and word count.
- Pauses: distinguish strategic pauses from silence caused by uncertainty.
- Vocal variety clues from text (e.g. trailing off, incomplete sentences, repetition).

### 2. Answer Quality
For each interview question asked:
- Quote the question
- Evaluate the answer: structure, clarity, conciseness, use of STAR method
- Did the candidate directly answer the question or dodge/ramble?
- Were examples specific or vague?
- How did the candidate handle difficult or unexpected questions?

### 3. Overall Communication
- Did the candidate ask good clarifying questions?
- Did they summarize or recap their points well?
- Were they concise or did they over-explain?
- Did they recover well from stumbles?

### 4. Coding Interview (only if this is a coding interview — skip entirely otherwise)
- Extract the exact coding question(s) asked
- Summarize the candidate's solution
- Did they clarify constraints before coding?
- Did they think out loud?
- Correctness of the solution
- Time/space complexity awareness
- Edge cases handled
- How they responded to hints or follow-up questions

---

## OUTPUT FORMAT

# Text-Based Analysis

### Speech Patterns
**Score: X/10**
**Filler word count:** [total] (~[X] per minute)
**Breakdown:** um: X, uh: X, like: X, you know: X, so: X, other: X
[Detailed feedback with example timestamps from the transcript]

### Answer Quality
**Score: X/10**

**Q: "[question]"** `[timestamp]`
[Evaluation of answer]

*(repeat for each question)*

### Overall Communication
**Score: X/10**
[Detailed feedback]

### Coding Interview Details
*(only if coding interview)*

**Question Asked:**
[Exact question]

**Candidate's Solution:**
[Description]

**Evaluation:**
- Correctness: ...
- Approach: ...
- Time complexity: ...
- Space complexity: ...
- Edge cases: ...
- Communication while coding: ...

---

TRANSCRIPT:
{transcript}
""".strip()


# ── Final report assembly prompt ──────────────────────────────────────────────

COMBINE_PROMPT_TEMPLATE = """\
You are an expert interview coach. You have two analysis documents for the same interview:

1. Visual Analysis — covers body language, eye contact, facial expressions (from watching the video)
2. Text Analysis — covers speech patterns, filler words, answer quality (from reading the transcript)

Combine them into one unified, polished final report in Markdown. Do not repeat information unnecessarily.
Cross-reference where relevant (e.g. "At [00:04:12] your body language tensed up AND your answer became vague").

Produce the report in this exact structure:

# Interview Performance Report
**Date analyzed:** {date}
**Company:** [from visual analysis]
**Interview type:** [from visual analysis]
**Overall rating:** [X/10 — weighted average across all dimensions]

---

## Executive Summary
[4-6 sentences. What kind of candidate does this person come across as overall?
Mention the strongest strength and most critical weakness.]

---

## What You Did Well ✓
[Bullet list — specific, with timestamps where available]

---

## What Needs Improvement ✗
[Bullet list — specific, with timestamps where available]

---

## Detailed Breakdown

### Body Language & Posture
**Score: X/10**
[From visual analysis]

### Eye Contact
**Score: X/10**
[From visual analysis]

### Facial Expressions
**Score: X/10**
[From visual analysis]

### Speech Patterns
**Score: X/10**
[From text analysis — include filler word count and frequency]

### Answer Quality
**Score: X/10**
[From text analysis — per question breakdown]

### Overall Presence
**Score: X/10**
[Combined impression]

---

## Coding Interview Details
*(Include only if this is a coding interview)*

### Question Asked
[Exact question]

### Candidate's Solution
[Description]

### Solution Evaluation
- **Correctness:**
- **Approach:**
- **Time complexity:**
- **Space complexity:**
- **Edge cases handled:**
- **Communication while coding:**

---

## Top 5 Priority Improvements
1.
2.
3.
4.
5.

---

## Action Plan
[Concrete, specific exercises or practices for each priority improvement]

---
*Report generated by Interview Prep Generator — Video Analyzer*

---

## SOURCE DOCUMENTS

### Visual Analysis
{visual_analysis}

---

### Text Analysis
{text_analysis}
""".strip()


# ── Call 4: Interview Intelligence document ───────────────────────────────────

INTEL_PROMPT_TEMPLATE = """\
You are an expert interview analyst. Below is the full transcript of a recorded interview.

Extract and organize the following information into a structured Interview Intelligence document.
Be thorough and specific — pull exact quotes, exact tool names, and exact question wording from the transcript.

---

TRANSCRIPT:
{transcript}

---

Produce the document in this exact Markdown structure:

# Interview Intelligence Report
**Date:** {date}
**Company:** [Extract from transcript. Look for company name mentioned by the interviewer, in introductions, or inferred from context. If not found write "Unknown".]
**Interviewee:** {interviewee_name}
**Interviewer:** {interviewer_name}
**Interview Type:** [Behavioral / Technical / System Design / Coding / Mixed]
**Duration:** [Estimated from timestamps]

---

## Interview Summary
[A detailed 6-10 sentence summary of the entire interview. Cover: what role was being interviewed for, what topics were explored, how the conversation flowed, notable moments, and the overall impression of how it went. Be specific — mention actual topics discussed, not vague descriptions.]

---

## All Questions & Answers

[For every question the interviewer asked, provide a full entry. Include small talk and intro questions too.]

### Q1: "[Exact question text]" `[timestamp]`
**Type:** [Behavioral / Technical / Situational / Clarifying / Small talk]
**Answer Summary:** [3-5 sentences summarizing what the interviewee said. Be specific — mention actual examples, companies, tools, or stories they referenced.]
**Direct Quote:** "[Pull a key sentence or two verbatim from the transcript that captures the core of their answer]"
**Follow-up questions:** [Any follow-ups asked on this question, or "None"]

*(repeat for every question — do not skip any)*

---

## Tools & Technologies Mentioned
[List every specific tool, technology, platform, service, or product mentioned by either speaker. Organize by category.]

### Cloud & Infrastructure
- [tool/service]: [who mentioned it and brief context]

### Containers & Orchestration
- [tool/service]: [context]

### CI/CD & DevOps
- [tool/service]: [context]

### Languages & Frameworks
- [tool/service]: [context]

### Databases & Storage
- [tool/service]: [context]

### Monitoring & Observability
- [tool/service]: [context]

### Security
- [tool/service]: [context]

### Other Tools
- [tool/service]: [context]

[Only include categories that have at least one item. Skip empty categories.]

---

## Technical Concepts & Topics Discussed
[List every technical concept, pattern, methodology, or architectural topic that came up. For each one, note who raised it and what was said about it.]

- **[Concept name]:** [1-2 sentences on how it came up and what was said]

*(list all — be exhaustive)*

---

## Key Stories & Examples Shared
[List every specific story, project, or example the interviewee used to answer questions. These are the STAR-method stories or concrete examples they pulled from their experience.]

### "[Story title based on content]"
- **Context:** [Which question it answered]
- **Company/Project:** [Where this story came from]
- **What they said:** [2-3 sentence summary of the actual content]
- **Timestamp:** [when it occurred]

---

## Topics NOT Covered
[Based on the job type and what was discussed, list 3-5 relevant technical or behavioral areas that were NOT explored in this interview but likely will come up in future rounds.]

---

## Interviewer Signals
[What signals did the interviewer give about what they care about? Did they push back on anything? Did they seem particularly interested in certain topics? Any hints about the team or role?]

---

*Generated by Interview Prep Generator — Video Analyzer*
""".strip()


def get_mime(filename: str) -> str | None:
    ext = filename.rsplit(".", 1)[-1].lower()
    return SUPPORTED_MIME.get(ext)


def analyze_video(
    client: genai.Client,
    video_path: str,
    filename: str,
    model: str = "gemini-2.0-flash-lite",
    status_callback=None,
    interviewee_name: str = "Candidate",
    interviewer_name: str = "Interviewer",
) -> tuple[str, str]:
    """
    Analyze an interview video using a cost-optimized 3-call strategy:
      Call 1 (video)     — transcript + visual analysis
      Call 2 (text only) — speech/content analysis from transcript
      Call 3 (text only) — combine both into final report

    Returns (report_markdown, transcript_markdown).
    """
    def log(msg):
        if status_callback:
            status_callback(msg)

    mime = get_mime(filename)
    if not mime:
        ext = filename.rsplit(".", 1)[-1].lower()
        raise ValueError(f"Unsupported video format: .{ext}. Supported: {', '.join(SUPPORTED_MIME)}")

    # ── Upload ────────────────────────────────────────────────────────────────
    log("Uploading video to Gemini...")
    with open(video_path, "rb") as f:
        video_file = client.files.upload(
            file=f,
            config=types.UploadFileConfig(mime_type=mime, display_name=filename),
        )

    log("Waiting for Gemini to process the video...")
    while video_file.state.name == "PROCESSING":
        time.sleep(3)
        video_file = client.files.get(name=video_file.name)

    if video_file.state.name == "FAILED":
        raise RuntimeError(f"Gemini video processing failed: {video_file.state}")

    video_part = types.Part.from_uri(file_uri=video_file.uri, mime_type=mime)

    # ── Call 1: Video → transcript + visual analysis ──────────────────────────
    log("Call 1/3 — Generating transcript and visual analysis (watching video)...")
    video_prompt = VIDEO_PROMPT_TEMPLATE.format(
        interviewee_name=interviewee_name,
        interviewer_name=interviewer_name,
    )
    video_response = client.models.generate_content(
        model=model,
        contents=[video_part, video_prompt],
        config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=8192),
    )
    video_output = video_response.text

    # Clean up video from Gemini servers — no longer needed
    try:
        client.files.delete(name=video_file.name)
    except Exception:
        pass

    # Split the video output into transcript and visual analysis
    # Both sections are clearly headed so we can split on the Visual Analysis header
    if "# Visual Analysis" in video_output:
        transcript_raw, visual_analysis = video_output.split("# Visual Analysis", 1)
        visual_analysis = "# Visual Analysis" + visual_analysis
    else:
        transcript_raw = video_output
        visual_analysis = video_output  # fallback — use full output for both

    # Extract just the transcript portion (Part 1)
    if "## PART 2" in transcript_raw:
        transcript = transcript_raw.split("## PART 2")[0].strip()
    else:
        transcript = transcript_raw.strip()

    # ── Call 2: Text only → speech + content analysis ─────────────────────────
    log("Call 2/4 — Analyzing speech patterns and answer quality (text only)...")
    text_response = client.models.generate_content(
        model=model,
        contents=TEXT_PROMPT_TEMPLATE.format(transcript=transcript),
        config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=8192),
    )
    text_analysis = text_response.text

    # ── Call 3: Text only → combine into final report ─────────────────────────
    log("Call 3/4 — Assembling final report...")
    combine_prompt = COMBINE_PROMPT_TEMPLATE.format(
        date=datetime.now().strftime("%B %d, %Y"),
        visual_analysis=visual_analysis,
        text_analysis=text_analysis,
    )
    final_response = client.models.generate_content(
        model=model,
        contents=combine_prompt,
        config=types.GenerateContentConfig(temperature=0.3, max_output_tokens=8192),
    )
    report = final_response.text

    # ── Call 4: Text only → interview intelligence document ───────────────────
    log("Call 4/4 — Extracting interview intelligence (Q&A, tools, concepts)...")
    intel_prompt = INTEL_PROMPT_TEMPLATE.format(
        transcript=transcript,
        date=datetime.now().strftime("%B %d, %Y"),
        interviewee_name=interviewee_name,
        interviewer_name=interviewer_name,
    )
    intel_response = client.models.generate_content(
        model=model,
        contents=intel_prompt,
        config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=8192),
    )
    intel = intel_response.text

    log("Done.")
    return report, transcript, intel
