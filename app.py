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

load_dotenv()

# Module-level store for background thread communication.
# st.session_state is not reliably writable from background threads,
# so we use a plain dict keyed by session ID instead.
# Removed: _analysis_jobs was a module-level dict but Streamlit reloads
# modules on every rerun, wiping it. Job dicts now live in st.session_state
# and are passed by reference to background threads, so thread writes are
# visible on the next rerun without any module-level state.

# ── Constants ────────────────────────────────────────────────────────────────
PINECONE_INDEX  = "interview-prep"
CHAT_MODEL      = "gemini-2.5-flash"
EMBED_MODEL     = "multilingual-e5-large"   # Pinecone integrated inference — free tier
NAMESPACE       = "__default__"
BASE_OUTPUT_DIR = Path(r"C:\Users\Sean Cancino\Documents\interview-prep")
BASE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

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
    if uploaded_file.name.endswith(".pdf"):
        from pypdf import PdfReader
        import io
        reader = PdfReader(io.BytesIO(uploaded_file.read()))
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    return uploaded_file.read().decode("utf-8")


def slugify(text: str) -> str:
    return text.replace(" ", "_").replace("/", "-")


def generate_doc(gemini_client, doc_key: str, resume: str, job_desc: str, company: str = "", role: str = "") -> str:
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

    resume_file = st.file_uploader("Upload Resume", type=["txt", "pdf"])
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

        # Create a new folder for this run: e.g. 05-30-26_Comcast
        run_dir = BASE_OUTPUT_DIR / f"{date_str}_{company_slug}"
        run_dir.mkdir(parents=True, exist_ok=True)
        st.session_state.run_dir = str(run_dir)

        if "generated_docs" not in st.session_state:
            st.session_state.generated_docs = {}

        # ── Phase 1: Generate all docs ────────────────────────────────────────
        progress = st.progress(0)
        status = st.empty()

        for i, key in enumerate(doc_keys):
            status.text(f"Generating {DOC_OPTIONS[key]}... ({i+1}/{len(doc_keys)})")
            content = generate_doc(gemini, key, resume_text, job_desc, company, role)
            header = f"<!-- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | Company: {company} | Role: {role} -->\n\n"
            full_content = header + content

            filename = f"{date_str}_{company_slug}_{key}.md"
            filepath = run_dir / filename
            filepath.write_text(full_content, encoding="utf-8")

            st.session_state.generated_docs[key] = {
                "content": full_content,
                "filename": filename,
                "company": company_slug,
                "doc_type": key,
                "date": date_str,
            }
            progress.progress((i + 1) / (len(doc_keys) + 1))  # +1 reserves space for indexing phase

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

    if st.button("Clear Chat"):
        st.session_state.messages = []
        st.rerun()

    filters = {}

    if "messages" not in st.session_state:
        st.session_state.messages = []

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
                response = rag_answer(index, gemini, prompt, filters)
            st.markdown(response)

        st.session_state.messages.append({"role": "assistant", "content": response})


# ── Video analysis background worker ─────────────────────────────────────────
def _run_analysis_thread(job: dict, gemini, tmp_path, video_filename, model_choice, company, interviewee_name, interviewer_name, video_type):
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
            study_guide, transcript = analyze_tech_prep(
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

            run_dir = BASE_OUTPUT_DIR / f"{date_str}_{company_slug}"
            run_dir.mkdir(parents=True, exist_ok=True)

            guide_filename      = f"{date_str}_{company_slug}_{video_stem}_tech_prep.md"
            transcript_filename = f"{date_str}_{company_slug}_{video_stem}_transcript.md"

            (run_dir / guide_filename).write_text(study_guide, encoding="utf-8")
            (run_dir / transcript_filename).write_text(transcript, encoding="utf-8")

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

        else:
            # ── Interview flow ────────────────────────────────────────────────
            update_status("Starting interview analysis...")
            report, transcript, intel = analyze_video(
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
                detected = "Unknown"
                for line in report.splitlines():
                    if line.startswith("**Company:**"):
                        detected = line.split("**Company:**", 1)[-1].strip()
                        break
                company_slug = slugify(detected) if detected.lower() != "unknown" else "Unknown"

            run_dir = BASE_OUTPUT_DIR / f"{date_str}_{company_slug}"
            run_dir.mkdir(parents=True, exist_ok=True)

            filename            = f"{date_str}_{company_slug}_{video_stem}_analysis.md"
            transcript_filename = f"{date_str}_{company_slug}_{video_stem}_transcript.md"
            intel_filename      = f"{date_str}_{company_slug}_{video_stem}_intel.md"

            (run_dir / filename).write_text(report,      encoding="utf-8")
            (run_dir / transcript_filename).write_text(transcript, encoding="utf-8")
            (run_dir / intel_filename).write_text(intel, encoding="utf-8")

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
    from analyzer import get_mime, SUPPORTED_MIME

    st.header("Analyze Interview Video")

    _qwen = has_qwen()
    _groq = bool(os.getenv("GROQ_API_KEY", "").strip())

    if _qwen and _groq:
        st.success(
            "**Full hybrid mode** — Qwen2.5-VL for visual analysis, "
            "Groq Whisper (free) for transcription, Gemini for speaker labels + analysis."
        )
    elif _qwen:
        st.success(
            "**Hybrid mode** — Qwen2.5-VL for visual analysis, Gemini for audio transcription. "
            "Add `GROQ_API_KEY` to .env to make transcription free."
        )
    else:
        st.info(
            "**Gemini-only mode** — Add `DASHSCOPE_API_KEY` (Qwen) and `GROQ_API_KEY` (Groq) "
            "to your .env to enable full hybrid mode and cut costs ~10x."
        )

    st.caption(
        "Upload a recorded interview video. The AI will generate "
        "a detailed feedback report covering body language, speech, content quality, and more. "
        "For coding interviews it will also extract the question and evaluate your solution."
    )

    col1, col2 = st.columns(2)
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
            help="2.0 Flash Lite: cheapest (~$0.03/30min). 2.5 Flash: best value (~$0.08, recommended). 2.5 Pro: highest quality (~$1.25).",
        )

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

    supported_exts = ", ".join(f".{e}" for e in SUPPORTED_MIME)
    video_file = st.file_uploader(
        f"Upload Interview Video ({supported_exts})",
        type=list(SUPPORTED_MIME.keys()),
        key="av_video",
    )

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
                args=(new_job, gemini, tmp.name, video_file.name, model_choice, company, interviewee_name, interviewer_name, video_type),
                daemon=True,
            )
            thread.start()
            st.rerun()
        except Exception as e:
            import traceback
            st.error(f"Failed to start analysis: {e}\n\n```\n{traceback.format_exc()}\n```")

    # Re-read job from session_state each render (thread may have updated it)
    job = st.session_state.get("av_job", {})
    job_state = job.get("state", "idle")

    if job_state == "running":
        status_msg = job.get("status", "Working...")
        st.info(f"⏳ {status_msg}")
        time.sleep(3)
        st.rerun()

    elif job_state == "done":
        if job.get("result"):
            st.session_state.video_report = job["result"]
        st.success(job.get("status", "Done!"))

    elif job_state == "error":
        st.error(job.get("status", "An error occurred."))

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


# ── App Shell ─────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Interview Prep Generator",
    page_icon="🎯",
    layout="wide",
)

st.title("Interview Prep Generator")

tab1, tab2, tab3 = st.tabs(["Generate Documents", "Analyze Video", "Chat"])

with tab1:
    page_generate()

with tab2:
    page_analyze()

with tab3:
    page_chat()
