import os
import re
import sys
import time
import threading
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pinecone import Pinecone
from cost_tracker import CostTracker

load_dotenv()

# Module-level store for background thread communication.
# st.session_state is not reliably writable from background threads,
# so we use a plain dict keyed by session ID instead.
# Removed: _analysis_jobs was a module-level dict but Streamlit reloads
# modules on every rerun, wiping it. Job dicts now live in st.session_state
# and are passed by reference to background threads, so thread writes are
# visible on the next rerun without any module-level state.

# ── Constants ────────────────────────────────────────────────────────────────
PINECONE_INDEX       = "interview-prep"
CHAT_MODEL           = "gemini-2.5-flash"
EMBED_MODEL          = "multilingual-e5-large"
NAMESPACE            = "__default__"
DEFAULT_OUTPUT_DIR   = Path(os.getenv("OUTPUT_DIR", "/app/output"))
CONFIG_FILE          = Path(__file__).parent / ".app_config.json"


def load_config() -> dict:
    if CONFIG_FILE.exists():
        import json
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_config(cfg: dict):
    import json
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def get_output_dir() -> Path:
    """Return the current documents directory from config or default."""
    cfg = load_config()
    p = Path(cfg.get("output_dir", str(DEFAULT_OUTPUT_DIR)))
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_typed_output_dir(subfolder: str) -> Path:
    """Return output_dir/subfolder, unless output_dir already ends with subfolder."""
    base = get_output_dir()
    return base if base.name == subfolder else base / subfolder


BASE_OUTPUT_DIR = get_output_dir()

DOC_OPTIONS = {
    "story":      "The Complete Story",
    "playbook":   "Interview Prep Playbook",
    "mock_qa":    "Mock Interview Q&A",
    "narratives": "Profile Narratives",
    "tools":      "Tools Narratives",
    "research":   "Company Research",
}

# Docs that don't require a resume upload
RESUME_NOT_REQUIRED = {"research"}

# ── Clients ──────────────────────────────────────────────────────────────────
@st.cache_resource
def get_gemini():
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        st.error("GEMINI_API_KEY not set in .env")
        st.stop()
    return genai.Client(api_key=key)


def has_qwen():
    return bool(os.getenv("DASHSCOPE_API_KEY", "").strip())


@st.cache_resource
def get_pinecone_index():
    key = os.getenv("PINECONE_API_KEY")
    if not key:
        st.error("PINECONE_API_KEY not set in .env")
        st.stop()
    pc = Pinecone(api_key=key)
    existing = [i.name for i in pc.list_indexes()]
    if PINECONE_INDEX not in existing:
        pc.create_index_for_model(
            name=PINECONE_INDEX,
            cloud="aws",
            region="us-east-1",
            embed={
                "model": EMBED_MODEL,
                "field_map": {"text": "chunk_text"},
            },
        )
    return pc.Index(PINECONE_INDEX)


# ── Helpers ──────────────────────────────────────────────────────────────────
def read_resume(uploaded_file) -> str:
    import io
    name = uploaded_file.name.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(uploaded_file.read()))
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    if name.endswith(".docx"):
        import docx as _docx
        doc = _docx.Document(io.BytesIO(uploaded_file.read()))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    # .txt, .md, .srt, .vtt and any other text format
    return uploaded_file.read().decode("utf-8", errors="replace")


def slugify(text: str) -> str:
    # Strip characters that are illegal in Windows/Linux filenames and markdown markers.
    text = re.sub(r'[\\/:*?"<>|]', '', text)
    return re.sub(r'\s+', '_', text.strip()) or "Unknown"


# ── S3 helpers ────────────────────────────────────────────────────────────────
_S3_BUCKET = os.getenv("S3_BUCKET")          # unset locally → S3 upload skipped
_s3_client = None


def _get_s3():
    global _s3_client
    if _s3_client is None:
        import boto3
        _s3_client = boto3.client("s3")
    return _s3_client


def save_and_upload(path: Path, content: str, s3_key: str | None = None) -> None:
    """Write content to local path, then mirror to S3 if S3_BUCKET is configured."""
    path.write_text(content, encoding="utf-8")
    if _S3_BUCKET:
        key = s3_key or "/".join(path.parts[-3:])   # subfolder/run_dir/filename
        try:
            _get_s3().put_object(
                Bucket=_S3_BUCKET,
                Key=key,
                Body=content.encode("utf-8"),
                ContentType="text/markdown",
            )
        except Exception as exc:
            # Never block the user over a storage failure — log and continue.
            import traceback
            print(f"[S3 upload failed] {key}: {exc}\n{traceback.format_exc()}")


def generate_doc(gemini_client, doc_key: str, resume: str, job_desc: str, company: str = "", role: str = "") -> tuple[str, object]:
    """Returns (text, response) — response carries usage_metadata for cost tracking."""
    from generators import (
        generate_story, generate_playbook, generate_mock_qa,
        generate_narratives, generate_tools, generate_research,
    )
    if doc_key == "research":
        return generate_research(gemini_client, company, role, job_desc)
    fn_map = {
        "story":      generate_story,
        "playbook":   generate_playbook,
        "mock_qa":    generate_mock_qa,
        "narratives": generate_narratives,
        "tools":      generate_tools,
    }
    return fn_map[doc_key](gemini_client, resume, job_desc)


def chunk_markdown(text: str, meta: dict) -> list[dict]:
    chunks = []
    sections = re.split(r"\n(?=#{2,3} )", text)
    for section in sections:
        section = section.strip()
        if not section or len(section) < 50:
            continue
        first_line = section.splitlines()[0].strip()
        title = re.sub(r"^#+\s*", "", first_line)
        chunks.append({"text": section, "title": title, **meta})
    return chunks


def ingest_doc(index, gemini_client, text: str, meta: dict) -> int:
    """Upsert text chunks directly — Pinecone handles embedding internally."""
    chunks = chunk_markdown(text, meta)
    if not chunks:
        return 0
    records = [
        {
            "_id":        f"{meta['company']}_{meta['doc_type']}_{meta['date']}_chunk{i}",
            "chunk_text": chunk["text"][:2000],
            "title":      chunk["title"],
            "company":    meta["company"],
            "doc_type":   meta["doc_type"],
            "date":       meta["date"],
        }
        for i, chunk in enumerate(chunks)
    ]
    # Upsert in batches of 100
    for i in range(0, len(records), 100):
        index.upsert_records(records=records[i:i+100], namespace=NAMESPACE)
    return len(records)


def rag_answer(index, gemini_client, query: str, filters: dict) -> str:
    """Search using Pinecone integrated inference — no embedding call needed."""
    search_kwargs = {
        "namespace": NAMESPACE,
        "inputs":    {"text": query},
        "top_k":     5,
        "fields":    ["chunk_text", "title", "company", "doc_type"],
    }
    if filters:
        search_kwargs["filter"] = {k: {"$eq": v} for k, v in filters.items()}

    results = index.search(**search_kwargs)

    hits = results.get("result", {}).get("hits", [])
    if not hits:
        return "No relevant documents found. Generate and index some docs first."

    # Build context
    context_parts = []
    for i, hit in enumerate(hits, 1):
        f = hit.get("fields", {})
        source = f"[{f.get('doc_type','')} | {f.get('company','')} | {f.get('title','')}]"
        context_parts.append(f"--- Source {i}: {source} ---\n{f.get('chunk_text','')}")
    context = "\n\n".join(context_parts)

    # Answer
    system = """You are an expert interview coach with access to a candidate's personalized interview prep documents. Be specific and direct — reference the actual content retrieved. If asked how to answer an interview question, give the full answer the candidate should use. No generic advice."""
    prompt = f"CONTEXT:\n{context}\n\nQUESTION:\n{query}"
    response = gemini_client.models.generate_content(
        model=CHAT_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.4,
        ),
    )
    return response.text


# ── Page: Generate ────────────────────────────────────────────────────────────
def page_generate():
    st.header("Generate Interview Prep Documents")

    col1, col2 = st.columns(2)
    with col1:
        company = st.text_input("Target Company", placeholder="e.g. Comcast")
    with col2:
        role = st.text_input("Target Role", placeholder="e.g. DevOps Engineer")

    resume_file = st.file_uploader("Upload Resume", type=["pdf", "docx", "txt", "md", "srt", "vtt"])
    job_desc = st.text_area("Paste Job Description", height=200)

    st.markdown("**Select documents to generate:**")
    cols = st.columns(len(DOC_OPTIONS))
    selected = {}
    for col, (key, label) in zip(cols, DOC_OPTIONS.items()):
        selected[key] = col.checkbox(label, value=True)

    doc_keys = [k for k, v in selected.items() if v]

    needs_resume = any(k not in RESUME_NOT_REQUIRED for k in doc_keys)
    ready = company and role and job_desc and doc_keys and (resume_file or not needs_resume)
    if needs_resume and not resume_file:
        st.caption("Upload a resume to generate the selected documents (not required for Company Research only).")

    if st.button("Generate", type="primary", disabled=not ready):
        gemini = get_gemini()
        resume_text = read_resume(resume_file) if resume_file else ""
        date_str = datetime.now().strftime("%m-%d-%y")
        company_slug = slugify(company)

        run_dir = get_typed_output_dir("prep-docs") / f"{date_str}_{company_slug}"
        run_dir.mkdir(parents=True, exist_ok=True)
        st.session_state.run_dir = str(run_dir)

        if "generated_docs" not in st.session_state:
            st.session_state.generated_docs = {}

        # ── Phase 1: Generate all docs ────────────────────────────────────────
        from generators import MODEL as GEN_MODEL
        tracker = CostTracker(model=GEN_MODEL)
        progress = st.progress(0)
        status = st.empty()

        for i, key in enumerate(doc_keys):
            status.text(f"Generating {DOC_OPTIONS[key]}... ({i+1}/{len(doc_keys)})")
            content, response = generate_doc(gemini, key, resume_text, job_desc, company, role)
            tracker.add(DOC_OPTIONS[key], response)
            header = f"<!-- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | Company: {company} | Role: {role} -->\n\n"
            full_content = header + content

            filename = f"{date_str}_{company_slug}_{key}.md"
            filepath = run_dir / filename
            save_and_upload(filepath, full_content)

            st.session_state.generated_docs[key] = {
                "content": full_content,
                "filename": filename,
                "company": company_slug,
                "doc_type": key,
                "date": date_str,
            }
            progress.progress((i + 1) / (len(doc_keys) + 1))

        # ── Phase 2: Index all docs ───────────────────────────────────────────
        index = get_pinecone_index()
        docs_to_index = list(st.session_state.generated_docs.values())
        for i, doc in enumerate(docs_to_index):
            status.text(f"Uploading to Pinecone... ({i+1}/{len(docs_to_index)}) {DOC_OPTIONS.get(doc['doc_type'], doc['doc_type'])}")
            ingest_doc(index, gemini, doc["content"], {
                "company": doc["company"],
                "doc_type": doc["doc_type"],
                "date": doc["date"],
            })
            progress.progress((len(doc_keys) + i + 1) / (len(doc_keys) * 2))

        progress.progress(1.0)
        status.text("Done!")
        st.success(f"Generated and indexed {len(doc_keys)} document(s). Saved to: {run_dir}")
        with st.expander(f"💰 API Cost — ${tracker.total_cost:.4f}", expanded=False):
            st.markdown(tracker.summary())
        # Persist to cost log
        from cost_log import append_cost_record, build_record
        append_cost_record(build_record(
            "Generate Documents", tracker, company_slug,
            {"doc_keys": doc_keys, "role": role},
        ))

    # Show results + download buttons
    if st.session_state.get("generated_docs"):
        st.divider()
        st.subheader("Generated Documents")

        for key, doc in st.session_state.generated_docs.items():
            with st.expander(f"{DOC_OPTIONS.get(key, key)} — {doc['filename']}"):
                st.download_button(
                    label="Download .md",
                    data=doc["content"],
                    file_name=doc["filename"],
                    mime="text/markdown",
                    key=f"dl_{key}",
                )
                st.markdown(doc["content"][:3000] + ("\n\n*...truncated for preview*" if len(doc["content"]) > 3000 else ""))



# ── Page: Chat ────────────────────────────────────────────────────────────────
def page_chat():
    st.header("Chat with Your Prep Docs")

    # Keep the chat input fixed at the bottom and reduce Streamlit's default
    # block padding so the title sits closer to the top of the page.
    st.markdown(
        """
        <style>
        section[data-testid="stMain"] > div:first-child {
            padding-top: 1.5rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    if "messages" not in st.session_state:
        st.session_state.messages = []

    if st.session_state.messages and st.button("Clear Chat"):
        st.session_state.messages = []
        st.rerun()

    # Render existing messages
    if not st.session_state.messages:
        st.caption("Ask anything about your prep docs — stories, model answers, technical deep dives, video feedback, and more.")
    else:
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    if prompt := st.chat_input("Ask anything about your interview prep..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("Searching docs..."):
                index = get_pinecone_index()
                gemini = get_gemini()
                response = rag_answer(index, gemini, prompt, {})
            st.markdown(response)
        st.session_state.messages.append({"role": "assistant", "content": response})


# ── Video analysis background worker ─────────────────────────────────────────
def _run_analysis_thread(job: dict, gemini, tmp_path, video_filename, model_choice, company, interviewee_name, interviewer_name, video_type, frames_per_second: float = 0.1, audio_only: bool = False):
    """
    Runs in a background thread. Writes progress + results into `job` dict
    (a plain Python dict, safe to write from any thread).
    """
    from analyzer import analyze_video

    def update_status(msg):
        job["status"] = msg

    try:
        from analyzer import analyze_video, analyze_tech_prep

        date_str    = datetime.now().strftime("%m-%d-%y")
        company_slug = slugify(company) if company else None
        video_stem  = video_filename.rsplit(".", 1)[0]

        if video_type == "Tech Prep":
            # ── Tech Prep flow ────────────────────────────────────────────────
            update_status("Starting tech prep analysis...")
            study_guide, transcript, cost_tracker = analyze_tech_prep(
                client=gemini,
                video_path=tmp_path,
                filename=video_filename,
                model=model_choice,
                status_callback=update_status,
                interviewee_name=interviewee_name,
                interviewer_name=interviewer_name,
            )
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

            if not company_slug:
                company_slug = "TechPrep"

            run_dir = get_typed_output_dir("tech-prep") / f"{date_str}_{company_slug}"
            run_dir.mkdir(parents=True, exist_ok=True)

            guide_filename      = f"{date_str}_{company_slug}_{video_stem}_tech_prep.md"
            transcript_filename = f"{date_str}_{company_slug}_{video_stem}_transcript.md"

            save_and_upload(run_dir / guide_filename,      study_guide)
            save_and_upload(run_dir / transcript_filename, transcript)

            update_status("Indexing into Pinecone...")
            index = get_pinecone_index()
            base_meta = {"company": company_slug, "date": date_str}
            guide_count      = ingest_doc(index, gemini, study_guide, {**base_meta, "doc_type": "tech_prep"})
            transcript_count = ingest_doc(index, gemini, transcript,  {**base_meta, "doc_type": "video_transcript"})

            job["result"] = {
                "video_type": "Tech Prep",
                "content": study_guide,
                "filename": guide_filename,
                "transcript": transcript,
                "transcript_filename": transcript_filename,
                "company": company_slug,
                "date": date_str,
                "run_dir": str(run_dir),
            }
            job["status"] = (
                f"Done! Saved to {run_dir} and indexed "
                f"({guide_count + transcript_count} chunks) — ask questions in the Chat tab."
            )
            job["cost_summary"] = cost_tracker.summary()
            job["cost_total"]   = cost_tracker.total_cost
            from cost_log import build_record
            job["cost_record"] = build_record(
                "Analyze Video", cost_tracker, company_slug,
                {"video_type": "Tech Prep"},
            )

        else:
            # ── Interview flow ────────────────────────────────────────────────
            update_status("Starting interview analysis...")
            report, transcript, intel, cost_tracker = analyze_video(
                client=gemini,
                video_path=tmp_path,
                filename=video_filename,
                model=model_choice,
                status_callback=update_status,
                interviewee_name=interviewee_name,
                interviewer_name=interviewer_name,
                frames_per_second=frames_per_second,
                audio_only=audio_only,
            )
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

            if not company_slug:
                detected = "Unknown"
                for line in report.splitlines():
                    if line.startswith("**Company:**"):
                        detected = line.split("**Company:**", 1)[-1].strip()
                        break
                company_slug = slugify(detected) if detected.lower() != "unknown" else "Unknown"

            run_dir = get_typed_output_dir("interview") / f"{date_str}_{company_slug}"
            run_dir.mkdir(parents=True, exist_ok=True)

            filename            = f"{date_str}_{company_slug}_{video_stem}_analysis.md"
            transcript_filename = f"{date_str}_{company_slug}_{video_stem}_transcript.md"
            intel_filename      = f"{date_str}_{company_slug}_{video_stem}_intel.md"

            save_and_upload(run_dir / filename,            report)
            save_and_upload(run_dir / transcript_filename, transcript)
            save_and_upload(run_dir / intel_filename,      intel)

            update_status("Indexing report, transcript, and intel into Pinecone...")
            index = get_pinecone_index()
            base_meta      = {"company": company_slug, "date": date_str}
            report_count   = ingest_doc(index, gemini, report,      {**base_meta, "doc_type": "video_analysis"})
            transcript_count = ingest_doc(index, gemini, transcript, {**base_meta, "doc_type": "video_transcript"})
            intel_count    = ingest_doc(index, gemini, intel,        {**base_meta, "doc_type": "video_intel"})

            job["result"] = {
                "video_type": "Interview",
                "content": report,
                "filename": filename,
                "transcript": transcript,
                "transcript_filename": transcript_filename,
                "intel": intel,
                "intel_filename": intel_filename,
                "company": company_slug,
                "doc_type": "video_analysis",
                "date": date_str,
                "run_dir": str(run_dir),
            }
            job["status"] = (
                f"Done! Saved to {run_dir} and indexed "
                f"({report_count + transcript_count + intel_count} chunks) — ask questions in the Chat tab."
            )
            job["cost_summary"] = cost_tracker.summary()
            job["cost_total"]   = cost_tracker.total_cost
            from cost_log import build_record
            job["cost_record"] = build_record(
                "Analyze Video", cost_tracker, company_slug,
                {"video_type": "Interview"},
            )

        job["state"] = "done"

    except Exception as e:
        import traceback
        err = str(e)
        if "input token count exceeds" in err or "maximum number of tokens" in err:
            job["status"] = (
                "❌ **Video too long for this model.**\n\n"
                "The video exceeds the model's context window (~60 min for 2.5 Flash).\n\n"
                "**Fix:** Switch the Model dropdown to **gemini-2.5-pro** (supports up to ~128 min) and try again."
            )
        else:
            job["status"] = f"Error: {e}\n\n```\n{traceback.format_exc()}\n```"
        job["state"] = "error"


# ── Page: Analyze Video ───────────────────────────────────────────────────────
def page_analyze():
    import tempfile, shutil
    from analyzer import get_mime, SUPPORTED_MIME, SUPPORTED_VIDEO_MIME, SUPPORTED_AUDIO_MIME, is_audio_file

    st.header("Analyze Interview Video")

    _groq = bool(os.getenv("GROQ_API_KEY", "").strip())

    if _groq:
        st.success(
            "**Full mode** — Gemini frame analysis for visuals, Groq Whisper (free) for transcription."
        )
    else:
        st.info(
            "**Standard mode** — Gemini frame analysis for visuals, Gemini for transcription. "
            "Add `GROQ_API_KEY` to .env to make transcription free."
        )

    st.caption(
        "Upload a recorded interview video. The AI will generate "
        "a detailed feedback report covering body language, speech, content quality, and more. "
        "For coding interviews it will also extract the question and evaluate your solution."
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        company = st.text_input("Company (optional)", placeholder="e.g. Comcast", key="av_company")
    with col2:
        model_choice = st.selectbox(
            "Model",
            options=[
                "gemini-2.0-flash-lite",
                "gemini-2.5-flash",
                "gemini-2.5-pro",
            ],
            index=1,
            key="av_model",
            help="2.0 Flash Lite: cheapest (~$0.01/30min). 2.5 Flash: best value (~$0.02, recommended). 2.5 Pro: highest quality (~$0.05).",
        )
    # Determine whether the currently uploaded file is a native audio file.
    # Read from session_state (previous rerun value) because the file_uploader
    # widget hasn't rendered yet at this point in the layout.
    _prev_upload = st.session_state.get("av_video")
    _uploaded_is_audio = bool(_prev_upload and hasattr(_prev_upload, "name") and is_audio_file(_prev_upload.name))

    with col3:
        # Frame Rate is irrelevant for audio files or Tech Prep (audio-only)
        if _uploaded_is_audio:
            st.caption("Frame rate N/A — audio file")
            frame_rate_label = "1 frame / 3s — hand gestures (recommended)"
        else:
            frame_rate_label = st.selectbox(
                "Frame Rate",
                options=[
                    "1 frame / 10s — posture & presence (cheapest)",
                    "1 frame / 3s — hand gestures (recommended)",
                    "1 frame / 1s — frequent gestures (3× cost)",
                ],
                index=1,
                key="av_frame_rate",
                help="Higher rates catch more hand gestures but increase cost proportionally. Eye contact detection works well at any rate.",
            )
    _frame_rate_map = {
        "1 frame / 10s — posture & presence (cheapest)": 0.1,
        "1 frame / 3s — hand gestures (recommended)":   1/3,
        "1 frame / 1s — frequent gestures (3× cost)":   1.0,
    }
    frames_per_second = _frame_rate_map[frame_rate_label]

    col_vtype, col_audio = st.columns([3, 2])
    with col_vtype:
        video_type = st.radio(
            "Video Type",
            options=["Interview", "Tech Prep"],
            horizontal=True,
            key="av_video_type",
            help=(
                "Interview: full analysis — visual feedback, speech patterns, performance report, intel doc. "
                "Tech Prep: transcript + study guide with all concepts, questions, and narratives to prepare."
            ),
        )
    with col_audio:
        if _uploaded_is_audio or video_type != "Interview":
            # Audio files are always audio-only; Tech Prep has no visual analysis anyway
            audio_only = True
        else:
            audio_only = st.checkbox(
                "🎙️ Audio only (skip visual analysis)",
                key="av_audio_only",
                help=(
                    "Skips frame extraction and visual analysis entirely. "
                    "Faster and cheaper — transcription, speech quality, and interview intelligence only. "
                    "Use when you don't need body language / eye contact feedback."
                ),
            )

    col3, col4 = st.columns(2)
    with col3:
        interviewee_name = st.text_input(
            "Your Name",
            placeholder="e.g. Sean Patrick",
            key="av_interviewee",
            help="Used to label your lines in the transcript.",
        )
    with col4:
        other_label = "Interviewer Name" if video_type == "Interview" else "Other Participant (optional)"
        interviewer_name = st.text_input(
            other_label,
            placeholder="e.g. John Smith (or leave blank)",
            key="av_interviewer",
            help="Leave blank to use 'Interviewer'." if video_type == "Interview" else "Leave blank to use 'Host'.",
        )

    interviewee_name = interviewee_name.strip() or "Candidate"
    interviewer_name = interviewer_name.strip() or ("Interviewer" if video_type == "Interview" else "Host")

    video_exts = " ".join(f".{e}" for e in SUPPORTED_VIDEO_MIME)
    audio_exts = " ".join(f".{e}" for e in SUPPORTED_AUDIO_MIME)
    video_file = st.file_uploader(
        f"Upload File  ·  Video: {video_exts}  ·  Audio: {audio_exts}",
        type=list(SUPPORTED_MIME.keys()),
        key="av_video",
    )

    # Auto-detect audio uploads and surface an info note
    if video_file and is_audio_file(video_file.name):
        st.info("🎙️ Audio file detected — visual analysis skipped automatically.")

    if video_file:
        size_mb = video_file.size / 1_000_000
        st.info(f"📁 **{video_file.name}** — {size_mb:.0f} MB")

    # Job dict lives in session_state so it survives reruns.
    # The background thread holds a reference to the same dict object,
    # so its writes are visible here on the next poll.
    job = st.session_state.get("av_job", {})
    job_state = job.get("state", "idle")

    ready = video_file is not None and job_state != "running"

    MAX_MINUTES = 60

    if st.button("Analyze Video", type="primary", disabled=not ready):
        try:
            # Copy uploaded file to disk
            suffix = "." + video_file.name.rsplit(".", 1)[-1]
            video_file.seek(0)
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            shutil.copyfileobj(video_file, tmp)
            tmp.close()

            # Check video duration before proceeding
            import av as _av
            with _av.open(tmp.name) as container:
                duration_sec = container.duration / 1_000_000  # av uses microseconds
            duration_min = duration_sec / 60

            if duration_min > MAX_MINUTES:
                os.unlink(tmp.name)
                st.error(
                    f"⛔ **Video is too long ({duration_min:.0f} min).** "
                    f"Maximum supported length is **{MAX_MINUTES} minutes**.\n\n"
                    f"Please trim the video to under {MAX_MINUTES} minutes and try again. "
                    f"You can trim for free using the Windows Photos app (open video → Edit → Trim)."
                )
                st.stop()

            # Store job dict in session_state; pass same reference to thread
            new_job = {"state": "running", "status": "Starting analysis...", "result": None}
            st.session_state["av_job"] = new_job

            gemini = get_gemini()
            thread = threading.Thread(
                target=_run_analysis_thread,
                args=(new_job, gemini, tmp.name, video_file.name, model_choice, company, interviewee_name, interviewer_name, video_type, frames_per_second, audio_only),
                daemon=True,
            )
            thread.start()
            st.rerun()
        except Exception as e:
            import traceback
            st.error(f"Failed to start analysis: {e}\n\n```\n{traceback.format_exc()}\n```")

    # ── Job status poller — runs every 3s without blocking other tabs ──────────
    def _parse_progress(status: str) -> float:
        """Estimate 0-1 progress from the analyzer's log message."""
        import re
        s = status.lower()
        # "Call N/M" or "Step N/M" — the bulk of the work
        m = re.search(r'(?:call|step)\s+(\d+)/(\d+)', s)
        if m:
            n, total = int(m.group(1)), int(m.group(2))
            # Calls fill 20%–88% of the bar; each call is an equal slice
            return 0.20 + (n - 1) / total * 0.68 + (0.68 / total) * 0.5
        if 'indexing' in s or 'pinecone' in s:
            return 0.92
        if 'frames extracted' in s:
            return 0.18
        if 'extracting video frames' in s:
            return 0.04
        if 'extracting audio' in s or 'starting' in s:
            return 0.10
        if 'done' in s or 'saved' in s:
            return 1.0
        return 0.05

    # Only poll when a job is actively running — stops background reruns when idle
    _current_job_state = st.session_state.get("av_job", {}).get("state", "idle")
    _poll_interval = 3 if _current_job_state == "running" else None

    @st.fragment(run_every=_poll_interval)
    def _job_status():
        job = st.session_state.get("av_job", {})
        state = job.get("state", "idle")
        if state == "running":
            status = job.get("status", "Working...")
            pct = _parse_progress(status)
            st.progress(pct)
            st.caption(f"⏳ {status}")
        elif state == "done":
            if job.get("result"):
                st.session_state.video_report = job["result"]
            st.success(job.get("status", "Done!"))
            if job.get("cost_summary"):
                with st.expander(f"💰 API Cost — ${job['cost_total']:.4f}", expanded=False):
                    st.markdown(job["cost_summary"])
            # Write cost record once (guard with flag so fragment doesn't double-log)
            if job.get("cost_record") and not job.get("cost_logged"):
                job["cost_logged"] = True
                from cost_log import append_cost_record
                append_cost_record(job["cost_record"])
        elif state == "error":
            st.error(job.get("status", "An error occurred."))

    _job_status()

    # Show results
    if st.session_state.get("video_report"):
        doc = st.session_state.video_report
        st.divider()

        if doc.get("video_type") == "Tech Prep":
            # ── Tech Prep results ─────────────────────────────────────────────
            col_g, col_t = st.columns(2)
            with col_g:
                st.download_button(
                    label="Download Study Guide (.md)",
                    data=doc["content"],
                    file_name=doc["filename"],
                    mime="text/markdown",
                    key="av_download_guide",
                )
            with col_t:
                st.download_button(
                    label="Download Transcript (.md)",
                    data=doc.get("transcript", ""),
                    file_name=doc.get("transcript_filename", "transcript.md"),
                    mime="text/markdown",
                    key="av_download_transcript",
                )

            tab_guide, tab_transcript = st.tabs(["Tech Prep Study Guide", "Transcript"])
            with tab_guide:
                st.markdown(doc["content"])
            with tab_transcript:
                st.markdown(doc.get("transcript", ""))

        else:
            # ── Interview results ─────────────────────────────────────────────
            col_r, col_t, col_i = st.columns(3)
            with col_r:
                st.download_button(
                    label="Download Report (.md)",
                    data=doc["content"],
                    file_name=doc["filename"],
                    mime="text/markdown",
                    key="av_download",
                )
            with col_t:
                st.download_button(
                    label="Download Transcript (.md)",
                    data=doc.get("transcript", ""),
                    file_name=doc.get("transcript_filename", "transcript.md"),
                    mime="text/markdown",
                    key="av_download_transcript",
                )
            with col_i:
                st.download_button(
                    label="Download Intel (.md)",
                    data=doc.get("intel", ""),
                    file_name=doc.get("intel_filename", "intel.md"),
                    mime="text/markdown",
                    key="av_download_intel",
                )

            tab_report, tab_intel, tab_transcript = st.tabs(["Performance Report", "Interview Intelligence", "Transcript"])
            with tab_report:
                st.markdown(doc["content"])
            with tab_intel:
                st.markdown(doc.get("intel", ""))
            with tab_transcript:
                st.markdown(doc.get("transcript", ""))


# ── Pinecone indexed-doc lookup ───────────────────────────────────────────────
def get_indexed_doc_keys(all_docs: list) -> set[str]:
    """
    Returns a set of 'company_doctype_date' strings that are already in Pinecone.
    Fetches chunk0 IDs for all docs in one batch call to check existence.
    """
    try:
        index = get_pinecone_index()
        # Build a map of chunk0_id -> doc_key for every doc
        id_map = {
            f"{d['company']}_{d['doc_type']}_{d['date']}_chunk0": f"{d['company']}_{d['doc_type']}_{d['date']}"
            for d in all_docs
        }
        if not id_map:
            return set()
        result = index.fetch(ids=list(id_map.keys()), namespace=NAMESPACE)
        # Result may be a dict or an object depending on SDK version
        if hasattr(result, "vectors"):
            found_ids = set(result.vectors.keys())
        elif isinstance(result, dict):
            found_ids = set(result.get("vectors", {}).keys())
        else:
            found_ids = set()
        return {id_map[vid] for vid in found_ids if vid in id_map}
    except Exception:
        return set()


# ── Page: Documents ──────────────────────────────────────────────────────────
def page_documents():
    st.header("Document Library")

    # ── Directory settings ────────────────────────────────────────────────────
    current_dir = get_output_dir()
    with st.expander("📂 Documents Directory", expanded=False):
        new_dir = st.text_input(
            "Local documents folder",
            value=str(current_dir),
            key="docs_dir_input",
            help="All generated documents and video analysis outputs will be saved here.",
        )
        col_save, col_reset = st.columns([1, 1])
        with col_save:
            if st.button("Save", key="docs_dir_save"):
                p = Path(new_dir.strip())
                try:
                    p.mkdir(parents=True, exist_ok=True)
                    cfg = load_config()
                    cfg["output_dir"] = str(p)
                    save_config(cfg)
                    st.success(f"Directory updated to `{p}`")
                    st.rerun()
                except Exception as e:
                    st.error(f"Invalid path: {e}")
        with col_reset:
            if st.button("Reset to default", key="docs_dir_reset"):
                cfg = load_config()
                cfg["output_dir"] = str(DEFAULT_OUTPUT_DIR)
                save_config(cfg)
                st.success(f"Reset to `{DEFAULT_OUTPUT_DIR}`")
                st.rerun()

    st.info(f"Showing local documents from `{current_dir}`")

    # ── Load documents ────────────────────────────────────────────────────────
    all_docs = []

    docs_dir = get_output_dir()
    if not docs_dir.exists():
        st.info("No documents found yet. Generate some docs first.")
        return
    # All known doc types — checked as exact suffixes against the filename stem
    _ALL_DOCTYPES = [
        "mock_qa", "tech_prep",          # multi-word first (longer match wins)
        "video_analysis", "video_intel", "video_transcript",
        "story", "playbook", "narratives", "tools", "research",
        "analysis", "intel", "transcript",  # short video suffixes as fallback
    ]
    _SHORT_TO_FULL = {
        "analysis":   "video_analysis",
        "intel":      "video_intel",
        "transcript": "video_transcript",
    }

    for run_folder in sorted(docs_dir.iterdir(), reverse=True):
        if not run_folder.is_dir():
            continue
        # Extract date + company from folder name (always clean, e.g. 06-01-26_TechInnovate_Solutions)
        folder_parts = run_folder.name.split("_", 1)
        folder_date    = folder_parts[0] if len(folder_parts) > 0 else ""
        folder_company = folder_parts[1] if len(folder_parts) > 1 else ""

        for md_file in sorted(run_folder.glob("*.md")):
            stem = md_file.stem

            detected_type = md_file.stem  # fallback
            for dtype in _ALL_DOCTYPES:
                if stem.endswith(f"_{dtype}"):
                    detected_type = _SHORT_TO_FULL.get(dtype, dtype)
                    break

            all_docs.append({
                "path":     md_file,
                "folder":   run_folder.name,
                "date":     folder_date,
                "company":  folder_company,
                "doc_type": detected_type,
                "filename": md_file.name,
                "size_kb":  round(md_file.stat().st_size / 1024, 1),
            })

    if not all_docs:
        st.info("No documents found yet. Generate some docs first.")
        return

    # ── Fetch Pinecone indexed keys ───────────────────────────────────────────
    with st.spinner("Checking Pinecone index..."):
        indexed_keys = get_indexed_doc_keys(all_docs)

    # ── Search / filter ───────────────────────────────────────────────────────
    col_search, col_company, col_type = st.columns([3, 2, 2])
    with col_search:
        search = st.text_input("Search", placeholder="Search by company, doc type, or filename...")
    with col_company:
        companies = ["All"] + sorted({d["company"] for d in all_docs if d["company"]})
        company_filter = st.selectbox("Company", companies)
    with col_type:
        doc_types = ["All"] + sorted({d["doc_type"] for d in all_docs if d["doc_type"]})
        type_filter = st.selectbox("Doc Type", doc_types)

    filtered = all_docs
    if search:
        q = search.lower()
        filtered = [d for d in filtered if q in d["filename"].lower()
                    or q in d["company"].lower() or q in d["doc_type"].lower()]
    if company_filter != "All":
        filtered = [d for d in filtered if d["company"] == company_filter]
    if type_filter != "All":
        filtered = [d for d in filtered if d["doc_type"] == type_filter]

    st.caption(f"{len(filtered)} document(s) found")

    if not filtered:
        st.warning("No documents match your search.")
        return

    st.divider()

    # ── Group by folder ───────────────────────────────────────────────────────
    folders: dict[str, list] = {}
    for doc in filtered:
        folders.setdefault(doc["folder"], []).append(doc)

    for folder_name, docs in folders.items():
        label = f"📁 {folder_name}  ({len(docs)} file{'s' if len(docs) != 1 else ''})"
        with st.expander(label, expanded=True):
            for doc in docs:
                doc_key = f"{doc['company']}_{doc['doc_type']}_{doc['date']}"
                is_indexed = doc_key in indexed_keys

                col_name, col_size, col_dl, col_index = st.columns([5, 1, 1, 1])
                with col_name:
                    label = f"`{doc['doc_type']}`  —  {doc['filename']}"
                    if is_indexed:
                        label += "  ✅"
                    st.markdown(label)
                with col_size:
                    st.caption(f"{doc['size_kb']} KB")
                with col_dl:
                    dl_key = f"dl_{doc['path']}"
                    content = doc["path"].read_text(encoding="utf-8")
                    st.download_button(
                        label="Download",
                        data=content,
                        file_name=doc["filename"],
                        mime="text/markdown",
                        key=dl_key,
                    )
                with col_index:
                    idx_key = f"idx_{doc['path']}"
                    if is_indexed:
                        st.caption("✅ Indexed")
                    else:
                        if st.button("Index", key=idx_key, help="Add to Pinecone for chat"):
                            with st.spinner("Indexing..."):
                                index = get_pinecone_index()
                                gemini = get_gemini()
                                text = doc["path"].read_text(encoding="utf-8")
                                count = ingest_doc(index, gemini, text, {
                                    "company":  doc["company"],
                                    "doc_type": doc["doc_type"],
                                    "date":     doc["date"],
                                })
                            indexed_keys.add(doc_key)
                            st.rerun()


# ── Page: Mock Interview ──────────────────────────────────────────────────────
def _build_interview_summary_report(answers: list) -> str:
    from datetime import datetime
    lines = [f"# Mock Interview Summary — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"]
    scored = [a for a in answers if a["answer"] != "[Skipped]"]
    if scored:
        avg = sum(a["result"].get("score", 0) for a in scored) / len(scored)
        lines.append(f"**Average Score: {avg:.1f} / 10**\n")
    for i, entry in enumerate(answers, 1):
        result = entry["result"]
        lines.append(f"---\n\n## Q{i} — Score: {result.get('score', 0)}/10\n")
        lines.append(f"**Question:** {entry['question']}\n")
        lines.append(f"**Your Answer:** {entry['answer']}\n")
        lines.append(f"**Verdict:** {result.get('verdict', '')}\n")
        if result.get("strengths"):
            lines.append("**Strengths:**\n" + "\n".join(f"- {s}" for s in result["strengths"]) + "\n")
        if result.get("improvements"):
            lines.append("**Improvements:**\n" + "\n".join(f"- {s}" for s in result["improvements"]) + "\n")
        if result.get("missed_points"):
            lines.append("**Missed Points:**\n" + "\n".join(f"- {s}" for s in result["missed_points"]) + "\n")
        if result.get("model_snippet"):
            lines.append(f"**Model Snippet:** {result['model_snippet']}\n")
    return "\n".join(lines)


def page_interview():
    import hashlib
    import json as _json
    import streamlit.components.v1 as components
    from interview import generate_questions, score_answer, transcribe_mic_audio

    st.header("Mock Interview")

    iv = st.session_state

    if "iv_state" not in iv:
        iv.iv_state = "setup"

    # ── Setup ──────────────────────────────────────────────────────────────────
    if iv.iv_state == "setup":
        st.markdown(
            "Practice answering interview questions generated live from your prep documents. "
            "Each answer is transcribed from your voice and scored by AI against your prep material."
        )

        col1, col2 = st.columns(2)
        with col1:
            n_q = st.selectbox("Number of questions", [5, 10, 15], index=0, key="iv_n_q")
        with col2:
            company = st.text_input("Filter by company (optional)", placeholder="e.g. Comcast", key="iv_setup_company")

        tts_on = st.checkbox("Read questions aloud (browser TTS)", value=True, key="iv_tts_on")

        has_groq = bool(os.getenv("GROQ_API_KEY", "").strip())
        if has_groq:
            st.success("Groq Whisper ready — your spoken answers will be auto-transcribed.")
        else:
            st.info("No GROQ_API_KEY — you can type your answers instead.")

        if st.button("Start Interview", type="primary", key="iv_start"):
            with st.spinner(f"Generating {n_q} questions from your prep docs..."):
                index = get_pinecone_index()
                gemini = get_gemini()
                questions = generate_questions(index, gemini, n_q, company.strip(), tracker=iv.iv_cost_tracker)

            if not questions:
                st.error(
                    "No documents found in Pinecone. Generate and index some prep documents first, "
                    "then come back to start a mock interview."
                )
                return

            iv.iv_questions    = questions
            iv.iv_q_idx        = 0
            iv.iv_answers      = []
            iv.iv_company      = slugify(company.strip()) if company.strip() else ""
            iv.iv_tts_enabled  = tts_on
            iv.iv_should_speak = True
            iv.iv_audio_hash   = None
            iv.iv_cost_logged  = False
            iv.iv_cost_tracker = CostTracker(model=CHAT_MODEL)
            iv.iv_state        = "interviewing"
            st.rerun()

    # ── Active interview ───────────────────────────────────────────────────────
    elif iv.iv_state in ("interviewing", "answered"):
        questions = iv.iv_questions
        q_idx     = iv.iv_q_idx
        total     = len(questions)
        question  = questions[q_idx]

        # Progress bar + end button
        prog_col, stop_col = st.columns([6, 1])
        with prog_col:
            st.progress(q_idx / total, text=f"Question {q_idx + 1} of {total}")
        with stop_col:
            if st.button("End", key="iv_stop", help="Go to summary"):
                iv.iv_state = "summary"
                st.rerun()

        # ── TTS: speak the question once per question ──────────────────────────
        if iv.iv_tts_enabled and iv.get("iv_should_speak"):
            iv.iv_should_speak = False
            safe_q = _json.dumps(question)
            components.html(
                f"""<script>
                (function() {{
                    var syn = window.top.speechSynthesis || window.speechSynthesis;
                    var Utt  = window.top.SpeechSynthesisUtterance || SpeechSynthesisUtterance;
                    if (!syn || !Utt) return;
                    syn.cancel();
                    setTimeout(function() {{
                        var msg = new Utt({safe_q});
                        msg.rate  = 0.92;
                        msg.pitch = 1.0;
                        syn.speak(msg);
                    }}, 150);
                }})();
                </script>""",
                height=0,
            )

        # ── Question display ───────────────────────────────────────────────────
        st.markdown(f"### Question {q_idx + 1} of {total}")
        st.info(f"**{question}**")

        col_replay, _ = st.columns([1, 5])
        with col_replay:
            if iv.iv_tts_enabled and st.button("🔊 Replay", key=f"iv_replay_{q_idx}"):
                iv.iv_should_speak = True
                st.rerun()

        # ── Answer input (only while interviewing) ─────────────────────────────
        if iv.iv_state == "interviewing":
            has_groq = bool(os.getenv("GROQ_API_KEY", "").strip())

            if has_groq:
                audio = st.audio_input("🎙️ Record your answer", key=f"iv_audio_{q_idx}")

                if audio is not None:
                    audio_bytes = audio.read()
                    audio_hash  = hashlib.md5(audio_bytes).hexdigest()

                    if iv.get("iv_audio_hash") != audio_hash:
                        iv.iv_audio_hash = audio_hash
                        with st.spinner("Transcribing..."):
                            transcript = transcribe_mic_audio(audio_bytes, getattr(audio, "type", "audio/webm"))
                        st.session_state[f"iv_edit_{q_idx}"] = transcript
                        st.rerun()

                st.caption("Or type / edit your answer below:")
            else:
                st.caption("Type your answer below:")

            answer = st.text_area(
                "Your answer",
                key=f"iv_edit_{q_idx}",
                height=160,
                placeholder=(
                    "Record audio above — transcript will appear here automatically. "
                    "Or type your answer directly."
                ),
                label_visibility="collapsed",
            )

            col_sub, col_skip = st.columns([3, 1])
            with col_sub:
                if st.button(
                    "Submit Answer",
                    type="primary",
                    disabled=not (answer and answer.strip()),
                    key=f"iv_submit_{q_idx}",
                ):
                    with st.spinner("Scoring your answer..."):
                        index  = get_pinecone_index()
                        gemini = get_gemini()
                        result = score_answer(index, gemini, question, answer.strip(), iv.iv_company, tracker=iv.iv_cost_tracker)
                    iv.iv_answers.append({
                        "question": question,
                        "answer":   answer.strip(),
                        "result":   result,
                    })
                    iv.iv_state = "answered"
                    st.rerun()

            with col_skip:
                if st.button("Skip", key=f"iv_skip_{q_idx}"):
                    iv.iv_answers.append({
                        "question": question,
                        "answer":   "[Skipped]",
                        "result": {
                            "score": 0, "verdict": "Skipped",
                            "strengths": [], "improvements": [],
                            "missed_points": [], "model_snippet": "",
                        },
                    })
                    if q_idx >= total - 1:
                        iv.iv_state = "summary"
                    else:
                        iv.iv_q_idx       += 1
                        iv.iv_audio_hash   = None
                        iv.iv_should_speak = True
                        iv.iv_state        = "interviewing"
                    st.rerun()

        # ── Score display (answered state) ─────────────────────────────────────
        elif iv.iv_state == "answered":
            latest = iv.iv_answers[-1]
            result = latest["result"]
            score  = result.get("score", 0)

            score_color = "green" if score >= 8 else ("orange" if score >= 5 else "red")
            st.markdown(f"### :{score_color}[{score} / 10] — {result.get('verdict', '')}")

            col_s, col_i = st.columns(2)
            with col_s:
                strengths = result.get("strengths", [])
                if strengths:
                    st.markdown("**✅ Strengths**")
                    for s in strengths:
                        st.markdown(f"- {s}")
            with col_i:
                improvements = result.get("improvements", [])
                if improvements:
                    st.markdown("**🔧 Improvements**")
                    for imp in improvements:
                        st.markdown(f"- {imp}")

            missed = result.get("missed_points", [])
            if missed:
                st.markdown("**⚠️ Key points you didn't mention**")
                for mp in missed:
                    st.markdown(f"- {mp}")

            snippet = result.get("model_snippet", "")
            if snippet:
                with st.expander("💡 How to strengthen this answer"):
                    st.markdown(snippet)

            with st.expander("Your answer (transcript)", expanded=False):
                st.write(latest["answer"])

            is_last = q_idx >= total - 1
            if is_last:
                if st.button("View Summary →", type="primary", key="iv_to_summary"):
                    iv.iv_state = "summary"
                    st.rerun()
            else:
                if st.button("Next Question →", type="primary", key=f"iv_next_{q_idx}"):
                    iv.iv_q_idx       += 1
                    iv.iv_audio_hash   = None
                    iv.iv_should_speak = True
                    iv.iv_state        = "interviewing"
                    st.rerun()

    # ── Summary ────────────────────────────────────────────────────────────────
    elif iv.iv_state == "summary":
        answers = iv.get("iv_answers", [])
        scored  = [a for a in answers if a["answer"] != "[Skipped]"]

        # Log cost once when summary is first shown
        if not iv.get("iv_cost_logged") and iv.get("iv_cost_tracker"):
            iv.iv_cost_logged = True
            from cost_log import append_cost_record, build_record
            append_cost_record(build_record(
                "Mock Interview", iv.iv_cost_tracker, iv.get("iv_company", ""),
                {"n_questions": len(answers), "n_answered": len(scored)},
            ))

        if scored:
            avg = sum(a["result"].get("score", 0) for a in scored) / len(scored)
            score_color = "green" if avg >= 8 else ("orange" if avg >= 5 else "red")
            st.markdown(f"## Interview Complete")
            st.markdown(f"**Average Score: :{score_color}[{avg:.1f} / 10]** across {len(scored)} answered question(s)")
        else:
            st.markdown("## Interview Complete — No answers recorded.")

        st.divider()

        for i, entry in enumerate(answers):
            result = entry["result"]
            score  = result.get("score", 0)
            label  = f"Q{i+1} — {score}/10 — {entry['question'][:70]}{'...' if len(entry['question']) > 70 else ''}"
            with st.expander(label, expanded=False):
                st.markdown(f"**{result.get('verdict', '')}**")
                if entry["answer"] != "[Skipped]":
                    st.markdown(f"*Your answer:* {entry['answer'][:300]}{'...' if len(entry['answer']) > 300 else ''}")
                col_s2, col_i2 = st.columns(2)
                with col_s2:
                    if result.get("strengths"):
                        for s in result["strengths"]:
                            st.markdown(f"✅ {s}")
                with col_i2:
                    if result.get("improvements"):
                        for imp in result["improvements"]:
                            st.markdown(f"🔧 {imp}")
                if result.get("model_snippet"):
                    st.caption(f"💡 {result['model_snippet']}")

        st.divider()
        col_new, col_dl = st.columns(2)
        with col_new:
            if st.button("Start New Interview", type="primary", key="iv_new"):
                for k in [k for k in st.session_state if k.startswith("iv_")]:
                    del st.session_state[k]
                st.rerun()
        if answers:
            with col_dl:
                report = _build_interview_summary_report(answers)
                st.download_button(
                    "Download Summary (.md)",
                    data=report,
                    file_name="mock_interview_summary.md",
                    mime="text/markdown",
                    key="iv_dl",
                )


# ── Page: API Costs ──────────────────────────────────────────────────────────
def page_costs():
    from datetime import datetime
    import pandas as pd
    from cost_log import load_cost_log

    st.header("API Cost History")

    log = load_cost_log()

    if not log:
        st.info("No cost records yet. Records are saved automatically after every Generate, Analyze Video, or Mock Interview run.")
        return

    # Parse timestamps and add display fields
    for r in log:
        r["_dt"] = datetime.fromisoformat(r["timestamp"])
        r["_month"] = r["_dt"].strftime("%Y-%m")
        r["_month_label"] = r["_dt"].strftime("%b %Y")

    # Sort newest first
    log.sort(key=lambda r: r["_dt"], reverse=True)

    # ── Top metrics ───────────────────────────────────────────────────────────
    all_time   = sum(r["total_cost"] for r in log)
    now        = datetime.now()
    cur_month  = now.strftime("%Y-%m")
    prev_month = (now.replace(day=1) - __import__("datetime").timedelta(days=1)).strftime("%Y-%m")
    this_mo    = sum(r["total_cost"] for r in log if r["_month"] == cur_month)
    last_mo    = sum(r["total_cost"] for r in log if r["_month"] == prev_month)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("All-time total",  f"${all_time:.4f}")
    m2.metric("This month",      f"${this_mo:.4f}")
    m3.metric("Last month",      f"${last_mo:.4f}")
    m4.metric("Total runs",      len(log))

    st.divider()

    # ── Monthly breakdown table ───────────────────────────────────────────────
    with st.expander("📅 Monthly Breakdown by Tab", expanded=False):
        months = sorted({r["_month"] for r in log}, reverse=True)
        tabs_seen = sorted({r["tab"] for r in log})
        rows = []
        for mo in months:
            mo_records = [r for r in log if r["_month"] == mo]
            row = {"Month": datetime.strptime(mo, "%Y-%m").strftime("%b %Y")}
            mo_total = 0.0
            for tab in tabs_seen:
                tab_cost = sum(r["total_cost"] for r in mo_records if r["tab"] == tab)
                row[tab] = f"${tab_cost:.4f}" if tab_cost else "—"
                mo_total += tab_cost
            row["Month Total"] = f"${mo_total:.4f}"
            rows.append(row)
        if rows:
            st.dataframe(rows, width='stretch', hide_index=True)

    st.divider()

    # ── Filters ───────────────────────────────────────────────────────────────
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        month_options = ["All time"] + [
            datetime.strptime(m, "%Y-%m").strftime("%b %Y")
            for m in sorted({r["_month"] for r in log}, reverse=True)
        ]
        sel_month = st.selectbox("Month", month_options, key="costs_month")
    with col_f2:
        tab_options = ["All tabs"] + sorted({r["tab"] for r in log})
        sel_tab = st.selectbox("Tab", tab_options, key="costs_tab")
    with col_f3:
        company_options = ["All companies"] + sorted({r.get("company", "") for r in log if r.get("company")})
        sel_company = st.selectbox("Company", company_options, key="costs_company")

    # Apply filters
    filtered = log
    if sel_month != "All time":
        filtered = [r for r in filtered if r["_month_label"] == sel_month]
    if sel_tab != "All tabs":
        filtered = [r for r in filtered if r["tab"] == sel_tab]
    if sel_company != "All companies":
        filtered = [r for r in filtered if r.get("company") == sel_company]

    st.caption(f"{len(filtered)} run(s) — ${sum(r['total_cost'] for r in filtered):.4f} total")
    st.divider()

    # ── Run history ───────────────────────────────────────────────────────────
    if not filtered:
        st.info("No runs match the selected filters.")
        return

    for r in filtered:
        ts   = r["_dt"].strftime("%b %d %Y  %I:%M %p")
        comp = f" — {r['company']}" if r.get("company") else ""
        label = f"**${r['total_cost']:.4f}**  ·  {r['tab']}{comp}  ·  {ts}"

        with st.expander(label, expanded=False):
            # Meta row
            info_cols = st.columns(4)
            info_cols[0].caption(f"**Model:** {r.get('model', '—')}")
            info_cols[1].caption(f"**Input:** {r.get('input_tokens', 0):,} tokens")
            info_cols[2].caption(f"**Output:** {r.get('output_tokens', 0):,} tokens")

            # Extra meta (doc_keys, video_type, n_questions, etc.)
            extra_parts = []
            if r.get("video_type"):
                extra_parts.append(f"Video type: {r['video_type']}")
            if r.get("doc_keys"):
                extra_parts.append(f"Docs: {', '.join(r['doc_keys'])}")
            if r.get("n_questions") is not None:
                extra_parts.append(f"Questions: {r['n_questions']} ({r.get('n_answered', r['n_questions'])} answered)")
            if extra_parts:
                info_cols[3].caption("  ·  ".join(extra_parts))

            # Breakdown table
            calls = r.get("calls", [])
            if calls:
                st.markdown("**Breakdown**")
                rows = []
                for c in calls:
                    rows.append({
                        "Step": c["label"],
                        "Input tokens": f"{c['input_tokens']:,}",
                        "Output tokens": f"{c['output_tokens']:,}",
                        "Cost": f"${c['cost']:.5f}",
                    })
                # Add total row
                rows.append({
                    "Step": "**Total**",
                    "Input tokens": f"{r.get('input_tokens', 0):,}",
                    "Output tokens": f"{r.get('output_tokens', 0):,}",
                    "Cost": f"**${r['total_cost']:.5f}**",
                })
                st.dataframe(rows, width='stretch', hide_index=True)
            else:
                st.caption("No call-level breakdown available for this run.")


# ── App Shell ─────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Interview Prep Generator",
    page_icon="🎯",
    layout="wide",
)

st.title("Interview Prep Generator")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["Generate Documents", "Analyze Video", "Documents", "Chat", "Mock Interview", "API Costs"])

with tab1:
    page_generate()

with tab2:
    page_analyze()

with tab3:
    page_documents()

with tab4:
    page_chat()

with tab5:
    page_interview()

with tab6:
    page_costs()
