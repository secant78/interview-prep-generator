"""
Interview Video Analyzer — Hybrid Qwen + Gemini Strategy
- Frame extraction  → Qwen2.5-VL  (visual analysis: body language, eye contact, posture)
- Audio extraction  → Gemini       (transcription: full timestamped transcript)
- Call 3 (text)    → Gemini       (speech + answer quality analysis from transcript)
- Call 4 (text)    → Gemini       (combine visual + text into final report)
- Call 5 (text)    → Gemini       (interview intelligence: Q&A, tools, concepts)

Falls back to Gemini-only (video upload) if no DASHSCOPE_API_KEY is set.
"""

import base64
import os
import tempfile
import time
from datetime import datetime
from io import BytesIO

import av
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

FRAMES_PER_SECOND = 0.125   # 1 frame every 8 seconds
MAX_FRAMES        = 150      # cap for very long videos
FRAME_WIDTH       = 640
FRAME_HEIGHT      = 360
FRAME_QUALITY     = 65       # JPEG quality


# ── Frame & audio extraction ──────────────────────────────────────────────────

def extract_frames(video_path: str) -> list[str]:
    """Extract frames as base64 JPEG data-URIs at FRAMES_PER_SECOND."""
    frames = []
    interval = 1.0 / FRAMES_PER_SECOND

    with av.open(video_path) as container:
        stream = container.streams.video[0]
        duration = float(container.duration or 0) / 1_000_000

        next_t = 0.0
        for frame in container.decode(stream):
            t = float(frame.pts * stream.time_base)
            if t < next_t:
                continue
            img = frame.to_image().resize((FRAME_WIDTH, FRAME_HEIGHT))
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=FRAME_QUALITY)
            b64 = base64.b64encode(buf.getvalue()).decode()
            frames.append(f"data:image/jpeg;base64,{b64}")
            next_t = t + interval
            if len(frames) >= MAX_FRAMES:
                break

    return frames


def extract_audio(video_path: str) -> tuple[str | None, str | None]:
    """
    Extract audio track to a temp mp3 file at 32kbps (stays under Groq's 25MB limit
    even for 60-min videos). Returns (file_path, mime_type) or (None, None).
    """
    try:
        with av.open(video_path) as container:
            if not container.streams.audio:
                return None, None

        tmp = tempfile.mktemp(suffix=".mp3")
        with av.open(video_path) as in_c:
            in_audio = in_c.streams.audio[0]
            with av.open(tmp, "w") as out_c:
                out_audio = out_c.add_stream("libmp3lame", rate=16000)
                out_audio.bit_rate = 32_000          # 32kbps — voice quality, small file
                for frame in in_c.decode(in_audio):
                    frame.pts = None
                    for pkt in out_audio.encode(frame):
                        out_c.mux(pkt)
                for pkt in out_audio.encode(None):
                    out_c.mux(pkt)
        return tmp, "audio/mpeg"

    except Exception:
        # mp3 codec unavailable — try wav fallback
        try:
            import wave, struct
            tmp = tempfile.mktemp(suffix=".wav")
            all_samples = []
            sample_rate = 16000

            with av.open(video_path) as in_c:
                if not in_c.streams.audio:
                    return None, None
                in_audio = in_c.streams.audio[0]
                for frame in in_c.decode(in_audio):
                    rf = frame.reformat(sample_rate=sample_rate,
                                        layout="mono", format="s16")
                    arr = rf.to_ndarray().flatten().tolist()
                    all_samples.extend(arr)

            with wave.open(tmp, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(struct.pack(f"{len(all_samples)}h", *all_samples))

            return tmp, "audio/wav"
        except Exception:
            return None, None


# ── Groq Whisper transcription ───────────────────────────────────────────────

GROQ_WHISPER_MODEL = "whisper-large-v3"
GROQ_MAX_FILE_MB   = 24   # Groq limit is 25 MB; stay under with margin


def transcribe_with_groq(audio_path: str, groq_api_key: str) -> str:
    """
    Transcribe audio using Groq Whisper (free, ~6s for 30-min audio).
    Returns a raw timestamped transcript string (no speaker labels yet).
    """
    from groq import Groq

    file_mb = os.path.getsize(audio_path) / 1_000_000
    if file_mb > GROQ_MAX_FILE_MB:
        raise ValueError(
            f"Audio file is {file_mb:.1f} MB — exceeds Groq's {GROQ_MAX_FILE_MB} MB limit. "
            "Try a shorter video or reduce the bitrate."
        )

    client = Groq(api_key=groq_api_key)
    with open(audio_path, "rb") as f:
        result = client.audio.transcriptions.create(
            file=f,
            model=GROQ_WHISPER_MODEL,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )

    lines = []
    for seg in result.segments:
        t = seg.start
        h, m, s = int(t // 3600), int((t % 3600) // 60), int(t % 60)
        lines.append(f"[{h:02d}:{m:02d}:{s:02d}] {seg.text.strip()}")

    return "\n".join(lines)


# ── Speaker label prompt (Gemini text call after Groq) ────────────────────────

SPEAKER_LABEL_PROMPT = """\
You are given a raw timestamped transcript from an interview. The transcript has no speaker labels.

Add the correct speaker label to every line based on context:
- Questions, prompts, and short phrases are usually the interviewer.
- Longer detailed answers, stories, and explanations are usually the interviewee.
- Use transitions, topic shifts, and conversational patterns to determine speaker.

INTERVIEWEE NAME: {interviewee_name}
INTERVIEWER NAME: {interviewer_name}

RAW TRANSCRIPT:
{raw_transcript}

---

Produce the labeled transcript in this EXACT format — preserve all timestamps and all original words:

# Interview Transcript

## Speakers
- **{interviewee_name}** — Candidate / Interviewee
- **{interviewer_name}** — Interviewer

---

[HH:MM:SS] **{interviewee_name}**: Their exact words here.
[HH:MM:SS] **{interviewer_name}**: Their exact words here.

Rules:
- Do NOT paraphrase. Keep every word exactly as transcribed.
- Every line must have a speaker label.
- Never use generic labels — always use {interviewee_name} or {interviewer_name}.
""".strip()


# ── Qwen visual-only prompt ───────────────────────────────────────────────────

VISUAL_ONLY_PROMPT = """\
You are an expert interview coach reviewing a sequence of frames from a recorded interview video.

IMPORTANT: You are seeing frames only — there is no audio. Do NOT comment on anything \
speech-related (words, filler words, answers, questions). Focus exclusively on what is \
visually observable.

Interviewee: {interviewee_name}
Interviewer: {interviewer_name}

Detect the company from visual cues (logos, screen content, backgrounds, badges).

Produce this section in Markdown:

# Visual Analysis

**Company:** [detected company name, or "Unknown"]
**Interview type:** [Behavioral / Technical / Coding / General — infer from visual context]

### Body Language & Posture
**Score: X/10**
- Posture: [upright / slouched / mixed — with frame timestamps or approximate times]
- Hand gestures: [purposeful / distracting / absent]
- Fidgeting / nervous habits: [describe with approximate timestamps]
- Head nodding and active listening signals
- Overall physical presence

### Eye Contact
**Score: X/10**
- Consistency with camera/interviewer
- Pattern of looking away (thinking vs nerves vs reading notes)
- Notable moments where eye contact was strong or weak

### Facial Expressions
**Score: X/10**
- Genuine vs forced smiles
- Signs of nervousness or discomfort
- Expressiveness and engagement level
- Resting expression during listening

### Overall Visual Presence
**Score: X/10**
- First impression from body language alone
- Confidence signals
- Professional appearance
""".strip()


# ── Gemini audio transcription prompt ────────────────────────────────────────

TRANSCRIPT_PROMPT = """\
You are an expert transcriptionist. Below is the audio from a recorded interview.

Transcribe every word spoken by all participants.

SPEAKER NAMES:
- Interviewee (candidate): {interviewee_name}
- Interviewer: {interviewer_name}

Use these exact names throughout. Do NOT use "Candidate", "Speaker 1", or generic labels.

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
""".strip()


# ── Call 3: Text-only speech + content analysis ───────────────────────────────

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

---

## OUTPUT FORMAT

# Text-Based Analysis

### Speech Patterns
**Score: X/10**
**Filler word count:** [total] (~[X] per minute)
**Breakdown:** um: X, uh: X, like: X, you know: X, so: X, other: X
[Detailed feedback with example timestamps]

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

---

TRANSCRIPT:
{transcript}
""".strip()


# ── Call 4: Combine into final report ─────────────────────────────────────────

COMBINE_PROMPT_TEMPLATE = """\
You are an expert interview coach. You have two analysis documents for the same interview:

1. Visual Analysis — covers body language, eye contact, facial expressions (from video frames)
2. Text Analysis — covers speech patterns, filler words, answer quality (from audio transcript)

Combine them into one unified, polished final report in Markdown. Do not repeat information.
Cross-reference where relevant (e.g. "At ~4:12 your body language tensed AND your answer became vague").

# Interview Performance Report
**Date analyzed:** {date}
**Company:** [from visual analysis]
**Interview type:** [from visual analysis]
**Overall rating:** [X/10 — weighted average across all dimensions]

---

## Executive Summary
[4-6 sentences. Strongest strength and most critical weakness.]

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
*(Include only if coding interview)*

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

## SOURCE DOCUMENTS

### Visual Analysis
{visual_analysis}

---

### Text Analysis
{text_analysis}
""".strip()


# ── Call 5: Interview Intelligence ────────────────────────────────────────────

INTEL_PROMPT_TEMPLATE = """\
You are an expert interview analyst. Below is the full transcript of a recorded interview.

Extract and organize the following information into a structured Interview Intelligence document.
Be thorough and specific — pull exact quotes, exact tool names, and exact question wording.

---

TRANSCRIPT:
{transcript}

---

# Interview Intelligence Report
**Date:** {date}
**Company:** [Extract from transcript or write "Unknown"]
**Interviewee:** {interviewee_name}
**Interviewer:** {interviewer_name}
**Interview Type:** [Behavioral / Technical / System Design / Coding / Mixed]
**Duration:** [Estimated from timestamps]

---

## Interview Summary
[6-10 sentence detailed summary: role, topics explored, flow, notable moments, overall impression.]

---

## All Questions & Answers

### Q1: "[Exact question text]" `[timestamp]`
**Type:** [Behavioral / Technical / Situational / Clarifying / Small talk]
**Answer Summary:** [3-5 sentences — mention actual examples, companies, tools referenced.]
**Direct Quote:** "[Key sentence verbatim from transcript]"
**Follow-up questions:** [Any follow-ups, or "None"]

*(repeat for every question — do not skip any)*

---

## Tools & Technologies Mentioned

### Cloud & Infrastructure
- [tool]: [who mentioned it and context]

### Containers & Orchestration
- [tool]: [context]

### CI/CD & DevOps
- [tool]: [context]

### Languages & Frameworks
- [tool]: [context]

### Databases & Storage
- [tool]: [context]

### Monitoring & Observability
- [tool]: [context]

### Security
- [tool]: [context]

### Other Tools
- [tool]: [context]

[Skip empty categories]

---

## Technical Concepts & Topics Discussed
- **[Concept]:** [1-2 sentences on how it came up and what was said]

---

## Key Stories & Examples Shared

### "[Story title]"
- **Context:** [Which question it answered]
- **Company/Project:** [Where the story came from]
- **What they said:** [2-3 sentence summary]
- **Timestamp:** [when it occurred]

---

## Topics NOT Covered
[3-5 relevant areas not explored — prep gaps for future rounds]

---

## Interviewer Signals
[What the interviewer seemed to care about, any pushback, hints about team/role]

---

*Generated by Interview Prep Generator — Video Analyzer*
""".strip()


# ── Tech Prep Study Guide prompt ─────────────────────────────────────────────

TECH_PREP_PROMPT = """\
You are an expert technical interview coach. Below is a transcript of a tech prep session \
(a study session, mock interview, technical discussion, or prep call).

Your job is to extract everything useful and turn it into a comprehensive study guide the \
candidate can use to prepare for their upcoming interview.

Be exhaustive — do not summarize away details. Every specific tool, concept, question, or \
story mentioned is potentially important.

---

TRANSCRIPT:
{transcript}

---

# Tech Prep Study Guide
**Date:** {date}
**Participant:** {interviewee_name}
**Session Summary:** [2-3 sentences describing what kind of session this was and what was covered overall]

---

## Session Overview
[5-8 sentences covering: what topics were discussed, what the session focused on, any \
specific role or company context mentioned, and the overall depth of the conversation.]

---

## Technical Questions Covered
[List every technical question that was asked or discussed. For each question, write out \
a full recommended answer the candidate should prepare — using specifics from the transcript \
where available. Do NOT leave answers vague.]

### Q: "[Exact question text]"
**Recommended Answer:**
[Write a complete, polished answer the candidate should be able to deliver. 6-15 sentences. \
Include specific tools, methodologies, and examples. If a story or example was discussed in \
the transcript, incorporate it. If not, recommend what kind of example they should use.]

**Key points to hit:**
- [bullet]
- [bullet]
- [bullet]

**Timestamp:** [when it came up]

*(repeat for every question — do not skip any)*

---

## Technical Concepts to Master
[Every technical concept, tool, technology, or methodology mentioned. For each one, explain \
what it is and why it matters for the interview context.]

### [Concept / Tool Name]
**What it is:** [1-2 sentence definition]
**Why it matters for this interview:** [1-2 sentences connecting it to the role/company context]
**What you should be able to say about it:** [2-3 bullet points of specific talking points]
**Depth required:** [Surface / Working knowledge / Deep dive]

*(list every concept mentioned — be exhaustive)*

---

## Stories & Narratives to Prepare
[Based on the questions and topics discussed, list the STAR-format stories the candidate \
should prepare. For each story, provide a template based on what was discussed in the session.]

### Story: "[Descriptive title]"
**Answers this question type:** [Which questions this story addresses]
**Situation:** [What the setup should be — be specific about company/project context]
**Task:** [What their role/objective was]
**Action:** [What they specifically did — name tools and decisions]
**Result:** [Quantified outcome to aim for]
**From the transcript:** [Any specific details mentioned in the session that should be in this story]

*(list all recommended stories)*

---

## Topics to Study Deeper
[Based on gaps or areas that came up in the session that need more preparation. For each topic, \
give specific things to review.]

### [Topic]
**Why it came up:** [context from the transcript]
**What to study:**
- [specific subtopic or resource]
- [specific subtopic or resource]
**Target depth:** [Be able to define it / Explain the architecture / Walk through an implementation]

---

## Concepts Mentioned But Not Fully Discussed
[Any tool, term, or concept that came up briefly but was not deeply explored — these are \
areas where the interviewer might probe further.]

- **[Concept]:** [Brief note on what it is and what to prepare]

---

## Action Items Before the Interview
[Concrete, prioritized list of things to do based on this prep session. Ordered by importance.]

1. [Most critical — specific action]
2.
3.
4.
5.

---

## Key Phrases & Talking Points
[Specific phrases, framings, or ways of explaining things that came up in the session that \
worked well or were recommended. These are ready-to-use language the candidate can practice.]

- "[Phrase or talking point]"
- "[Phrase or talking point]"

---

*Generated by Interview Prep Generator — Tech Prep Analyzer*
""".strip()


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_mime(filename: str) -> str | None:
    ext = filename.rsplit(".", 1)[-1].lower()
    return SUPPORTED_MIME.get(ext)


def _build_qwen_client():
    """Return an OpenAI client pointed at DashScope, or None if no key."""
    key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not key:
        return None
    try:
        from openai import OpenAI
        return OpenAI(
            api_key=key,
            base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        )
    except ImportError:
        return None


# ── Tech Prep analyzer ───────────────────────────────────────────────────────

def analyze_tech_prep(
    client: genai.Client,
    video_path: str,
    filename: str,
    model: str = "gemini-2.0-flash-lite",
    status_callback=None,
    interviewee_name: str = "Candidate",
    interviewer_name: str = "Interviewer",
) -> tuple[str, str]:
    """
    Analyze a tech prep session video.
    Skips visual analysis entirely — only extracts audio, transcribes,
    adds speaker labels, then generates a Tech Prep Study Guide.

    Returns (study_guide_markdown, transcript_markdown).
    """

    def log(msg):
        if status_callback:
            status_callback(msg)

    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    use_groq  = bool(groq_key)
    total     = 3 if use_groq else 2

    # ── Extract audio ─────────────────────────────────────────────────────────
    svc = "Groq Whisper" if use_groq else "Gemini"
    log(f"Step 1/{total} — Extracting and transcribing audio ({svc})...")
    audio_path, audio_mime = extract_audio(video_path)

    if not audio_path:
        transcript = "# Tech Prep Transcript\n\n*No audio track detected in this video.*"
    elif use_groq:
        raw = transcribe_with_groq(audio_path, groq_key)
        log(f"Step 2/{total} — Adding speaker labels (Gemini text)...")
        label_response = client.models.generate_content(
            model=model,
            contents=SPEAKER_LABEL_PROMPT.format(
                interviewee_name=interviewee_name,
                interviewer_name=interviewer_name,
                raw_transcript=raw,
            ),
            config=types.GenerateContentConfig(
                temperature=0.1, max_output_tokens=8192
            ),
        )
        transcript = label_response.text
        try:
            os.unlink(audio_path)
        except Exception:
            pass
    else:
        with open(audio_path, "rb") as f:
            audio_file = client.files.upload(
                file=f,
                config=types.UploadFileConfig(
                    mime_type=audio_mime, display_name=filename
                ),
            )
        while audio_file.state.name == "PROCESSING":
            time.sleep(2)
            audio_file = client.files.get(name=audio_file.name)
        if audio_file.state.name == "FAILED":
            raise RuntimeError("Gemini audio processing failed.")

        audio_part = types.Part.from_uri(
            file_uri=audio_file.uri, mime_type=audio_mime
        )
        transcript_response = client.models.generate_content(
            model=model,
            contents=[
                audio_part,
                TRANSCRIPT_PROMPT.format(
                    interviewee_name=interviewee_name,
                    interviewer_name=interviewer_name,
                ),
            ],
            config=types.GenerateContentConfig(
                temperature=0.2, max_output_tokens=8192
            ),
        )
        transcript = transcript_response.text
        try:
            client.files.delete(name=audio_file.name)
            os.unlink(audio_path)
        except Exception:
            pass

    # ── Generate Tech Prep Study Guide ────────────────────────────────────────
    log(f"Step {total}/{total} — Generating Tech Prep Study Guide...")
    guide_response = client.models.generate_content(
        model=model,
        contents=TECH_PREP_PROMPT.format(
            transcript=transcript,
            date=datetime.now().strftime("%B %d, %Y"),
            interviewee_name=interviewee_name,
        ),
        config=types.GenerateContentConfig(
            temperature=0.3, max_output_tokens=8192
        ),
    )
    study_guide = guide_response.text

    log("Done.")
    return study_guide, transcript


# ── Main analyzer ─────────────────────────────────────────────────────────────

def analyze_video(
    client: genai.Client,
    video_path: str,
    filename: str,
    model: str = "gemini-2.0-flash-lite",
    status_callback=None,
    interviewee_name: str = "Candidate",
    interviewer_name: str = "Interviewer",
) -> tuple[str, str, str]:
    """
    Analyze an interview video using a hybrid Qwen + Gemini strategy.

    Strategy (if DASHSCOPE_API_KEY is set):
      Call 1 — Qwen2.5-VL:    visual analysis from extracted frames (no audio cost)
      Call 2 — Gemini audio:  transcript from extracted audio (audio tokens only)
      Call 3 — Gemini text:   speech + content analysis
      Call 4 — Gemini text:   combine into final report
      Call 5 — Gemini text:   interview intelligence doc

    Fallback (no DASHSCOPE_API_KEY):
      Original Gemini-only flow (video upload for transcript + visual).

    Returns (report_markdown, transcript_markdown, intel_markdown).
    """

    def log(msg):
        if status_callback:
            status_callback(msg)

    mime = get_mime(filename)
    if not mime:
        ext = filename.rsplit(".", 1)[-1].lower()
        raise ValueError(f"Unsupported format: .{ext}")

    qwen = _build_qwen_client()

    if qwen:
        return _analyze_hybrid(
            gemini=client,
            qwen=qwen,
            video_path=video_path,
            filename=filename,
            model=model,
            log=log,
            interviewee_name=interviewee_name,
            interviewer_name=interviewer_name,
        )
    else:
        log("No DASHSCOPE_API_KEY found — using Gemini-only mode.")
        return _analyze_gemini_only(
            client=client,
            video_path=video_path,
            filename=filename,
            mime=mime,
            model=model,
            log=log,
            interviewee_name=interviewee_name,
            interviewer_name=interviewer_name,
        )


# ── Hybrid path ───────────────────────────────────────────────────────────────

def _analyze_hybrid(gemini, qwen, video_path, filename, model, log,
                    interviewee_name, interviewer_name):

    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    use_groq  = bool(groq_key)
    total     = 6 if use_groq else 5

    # ── Extract frames ────────────────────────────────────────────────────────
    log("Extracting video frames for Qwen visual analysis...")
    frames = extract_frames(video_path)
    log(f"  {len(frames)} frames extracted.")

    # ── Extract audio ─────────────────────────────────────────────────────────
    svc = "Groq Whisper" if use_groq else "Gemini"
    log(f"Extracting audio track for {svc} transcription...")
    audio_path, audio_mime = extract_audio(video_path)
    log("  Audio extracted." if audio_path else "  No audio track found.")

    # ── Call 1: Qwen visual analysis ──────────────────────────────────────────
    log(f"Call 1/{total} — Visual analysis (Qwen2.5-VL, frames only)...")
    visual_prompt = VISUAL_ONLY_PROMPT.format(
        interviewee_name=interviewee_name,
        interviewer_name=interviewer_name,
    )
    qwen_response = qwen.chat.completions.create(
        model="qwen2.5-vl-72b-instruct",
        messages=[{
            "role": "user",
            "content": [
                {"type": "video", "video": frames, "fps": FRAMES_PER_SECOND},
                {"type": "text", "text": visual_prompt},
            ],
        }],
        max_tokens=4096,
    )
    visual_analysis = qwen_response.choices[0].message.content

    # ── Call 2: Transcription ─────────────────────────────────────────────────
    if not audio_path:
        transcript = "# Interview Transcript\n\n*No audio track detected in this video.*"
        call_offset = 2
    elif use_groq:
        # ── Groq Whisper: fast + free ─────────────────────────────────────────
        log(f"Call 2/{total} — Transcribing audio (Groq Whisper, free)...")
        raw_transcript = transcribe_with_groq(audio_path, groq_key)

        # ── Call 3: Gemini text — add speaker labels ──────────────────────────
        log(f"Call 3/{total} — Adding speaker labels (Gemini text)...")
        label_response = gemini.models.generate_content(
            model=model,
            contents=SPEAKER_LABEL_PROMPT.format(
                interviewee_name=interviewee_name,
                interviewer_name=interviewer_name,
                raw_transcript=raw_transcript,
            ),
            config=types.GenerateContentConfig(
                temperature=0.1, max_output_tokens=8192
            ),
        )
        transcript = label_response.text
        call_offset = 3

        try:
            os.unlink(audio_path)
        except Exception:
            pass
    else:
        # ── Gemini audio fallback ─────────────────────────────────────────────
        log(f"Call 2/{total} — Transcribing audio (Gemini)...")
        with open(audio_path, "rb") as f:
            audio_file = gemini.files.upload(
                file=f,
                config=types.UploadFileConfig(
                    mime_type=audio_mime, display_name=filename
                ),
            )
        while audio_file.state.name == "PROCESSING":
            time.sleep(2)
            audio_file = gemini.files.get(name=audio_file.name)
        if audio_file.state.name == "FAILED":
            raise RuntimeError("Gemini audio processing failed.")

        audio_part = types.Part.from_uri(
            file_uri=audio_file.uri, mime_type=audio_mime
        )
        transcript_response = gemini.models.generate_content(
            model=model,
            contents=[
                audio_part,
                TRANSCRIPT_PROMPT.format(
                    interviewee_name=interviewee_name,
                    interviewer_name=interviewer_name,
                ),
            ],
            config=types.GenerateContentConfig(
                temperature=0.2, max_output_tokens=8192
            ),
        )
        transcript = transcript_response.text
        call_offset = 2

        try:
            gemini.files.delete(name=audio_file.name)
            os.unlink(audio_path)
        except Exception:
            pass

    # ── Remaining text calls (Gemini) ─────────────────────────────────────────
    return _text_calls(
        gemini=gemini,
        model=model,
        transcript=transcript,
        visual_analysis=visual_analysis,
        log=log,
        interviewee_name=interviewee_name,
        interviewer_name=interviewer_name,
        call_offset=call_offset,
        total_calls=total,
    )


# ── Gemini-only fallback path ─────────────────────────────────────────────────

def _analyze_gemini_only(client, video_path, filename, mime, model, log,
                          interviewee_name, interviewer_name):

    log("Call 1/4 — Uploading video to Gemini...")
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

    # Build combined video prompt (transcript + visual)
    video_prompt = _GEMINI_VIDEO_PROMPT.format(
        interviewee_name=interviewee_name,
        interviewer_name=interviewer_name,
    )

    log("Call 1/4 — Generating transcript and visual analysis (watching video)...")
    video_response = client.models.generate_content(
        model=model,
        contents=[video_part, video_prompt],
        config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=8192),
    )
    video_output = video_response.text

    try:
        client.files.delete(name=video_file.name)
    except Exception:
        pass

    if "# Visual Analysis" in video_output:
        transcript_raw, visual_analysis = video_output.split("# Visual Analysis", 1)
        visual_analysis = "# Visual Analysis" + visual_analysis
    else:
        transcript_raw = video_output
        visual_analysis = video_output

    if "## PART 2" in transcript_raw:
        transcript = transcript_raw.split("## PART 2")[0].strip()
    else:
        transcript = transcript_raw.strip()

    return _text_calls(
        gemini=client,
        model=model,
        transcript=transcript,
        visual_analysis=visual_analysis,
        log=log,
        interviewee_name=interviewee_name,
        interviewer_name=interviewer_name,
        call_offset=1,
        total_calls=4,
    )


# ── Shared text-only calls (3-5 hybrid / 2-4 Gemini-only) ────────────────────

def _text_calls(gemini, model, transcript, visual_analysis, log,
                interviewee_name, interviewer_name, call_offset, total_calls):

    n = call_offset + 1

    log(f"Call {n}/{total_calls} — Analyzing speech patterns and answer quality...")
    text_response = gemini.models.generate_content(
        model=model,
        contents=TEXT_PROMPT_TEMPLATE.format(transcript=transcript),
        config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=8192),
    )
    text_analysis = text_response.text
    n += 1

    log(f"Call {n}/{total_calls} — Assembling final report...")
    combine_response = gemini.models.generate_content(
        model=model,
        contents=COMBINE_PROMPT_TEMPLATE.format(
            date=datetime.now().strftime("%B %d, %Y"),
            visual_analysis=visual_analysis,
            text_analysis=text_analysis,
        ),
        config=types.GenerateContentConfig(temperature=0.3, max_output_tokens=8192),
    )
    report = combine_response.text
    n += 1

    log(f"Call {n}/{total_calls} — Extracting interview intelligence...")
    intel_response = gemini.models.generate_content(
        model=model,
        contents=INTEL_PROMPT_TEMPLATE.format(
            transcript=transcript,
            date=datetime.now().strftime("%B %d, %Y"),
            interviewee_name=interviewee_name,
            interviewer_name=interviewer_name,
        ),
        config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=8192),
    )
    intel = intel_response.text

    log("Done.")
    return report, transcript, intel


# ── Gemini-only video prompt (fallback) ───────────────────────────────────────

_GEMINI_VIDEO_PROMPT = """\
You are an expert interview coach watching a recorded interview video.

SPEAKER NAMES:
- Interviewee (candidate): {interviewee_name}
- Interviewer: {interviewer_name}

Use these exact names. Do NOT use generic labels.

Your job has two parts. Produce both in a single response.

## PART 1 — FULL TRANSCRIPT

# Interview Transcript

## Speakers
- **{interviewee_name}** — Candidate
- **{interviewer_name}** — Interviewer

---

[HH:MM:SS] **{interviewee_name}**: Exact words spoken here.

Rules:
- Timestamp every new speaker turn AND every ~30 seconds.
- Transcribe exactly. Include filler words. Mark inaudible as [inaudible].

---

## PART 2 — VISUAL ANALYSIS

Analyze ONLY what can be observed visually. Do NOT comment on speech content.

# Visual Analysis

**Company:** [detected or "Unknown"]
**Interview type:** [Behavioral / Technical / Coding / General]

### Body Language & Posture
**Score: X/10**
[Details with timestamps]

### Eye Contact
**Score: X/10**
[Details]

### Facial Expressions
**Score: X/10**
[Details]

### Overall Visual Presence
**Score: X/10**
[Details]
""".strip()
