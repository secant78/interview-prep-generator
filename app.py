import os
import re
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pinecone import Pinecone, ServerlessSpec

load_dotenv()

# ── Constants ────────────────────────────────────────────────────────────────
PINECONE_INDEX = "interview-prep"
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 3072
CHAT_MODEL = "gemini-2.5-flash"
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


@st.cache_resource
def get_pinecone_index():
    key = os.getenv("PINECONE_API_KEY")
    if not key:
        st.error("PINECONE_API_KEY not set in .env")
        st.stop()
    pc = Pinecone(api_key=key)
    existing = {i.name: i for i in pc.list_indexes()}
    if PINECONE_INDEX in existing:
        # Recreate if dimension doesn't match (e.g. embedding model changed)
        if existing[PINECONE_INDEX].dimension != EMBEDDING_DIM:
            pc.delete_index(PINECONE_INDEX)
            existing.pop(PINECONE_INDEX)
    if PINECONE_INDEX not in existing:
        pc.create_index(
            name=PINECONE_INDEX,
            dimension=EMBEDDING_DIM,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
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


EMBED_DELAY = 6
MAX_RETRIES = 5


def embed_texts(gemini_client, texts: list[str]) -> list[list[float]]:
    import time
    all_embeddings = []
    for i, text in enumerate(texts):
        for attempt in range(MAX_RETRIES):
            try:
                result = gemini_client.models.embed_content(
                    model=EMBEDDING_MODEL,
                    contents=[text],
                    config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
                )
                all_embeddings.append(result.embeddings[0].values)
                break
            except Exception as e:
                if "429" in str(e) and attempt < MAX_RETRIES - 1:
                    time.sleep(EMBED_DELAY * (2 ** attempt))
                else:
                    raise
        if i < len(texts) - 1:
            time.sleep(EMBED_DELAY)
    return all_embeddings


def ingest_doc(index, gemini_client, text: str, meta: dict) -> int:
    chunks = chunk_markdown(text, meta)
    if not chunks:
        return 0
    texts = [c["text"] for c in chunks]
    embeddings = embed_texts(gemini_client, texts)
    vectors = [
        {
            "id": f"{meta['company']}_{meta['doc_type']}_{meta['date']}_chunk{i}",
            "values": emb,
            "metadata": {
                "text": chunk["text"][:2000],
                "title": chunk["title"],
                "company": meta["company"],
                "doc_type": meta["doc_type"],
                "date": meta["date"],
            },
        }
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings))
    ]
    for i in range(0, len(vectors), 100):
        index.upsert(vectors=vectors[i:i+100])
    return len(vectors)


def rag_answer(index, gemini_client, query: str, filters: dict) -> str:
    # Embed query
    result = gemini_client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=query,
        config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
    )
    embedding = result.embeddings[0].values

    # Retrieve
    query_kwargs = {"vector": embedding, "top_k": 5, "include_metadata": True}
    if filters:
        query_kwargs["filter"] = {k: {"$eq": v} for k, v in filters.items()}
    results = index.query(**query_kwargs)

    if not results.matches:
        return "No relevant documents found. Generate and index some docs first."

    # Build context
    context_parts = []
    for i, match in enumerate(results.matches, 1):
        m = match.metadata
        source = f"[{m.get('doc_type','')} | {m.get('company','')} | {m.get('title','')}]"
        context_parts.append(f"--- Source {i}: {source} ---\n{m.get('text','')}")
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

        index = get_pinecone_index()
        total_steps = len(doc_keys) * 2  # generate + index per doc
        progress = st.progress(0)
        status = st.empty()
        step = 0

        for i, key in enumerate(doc_keys):
            status.text(f"Generating {DOC_OPTIONS[key]}...")
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
            step += 1
            progress.progress(step / total_steps)

            status.text(f"Indexing {DOC_OPTIONS[key]}...")
            ingest_doc(index, gemini, full_content, {
                "company": company_slug,
                "doc_type": key,
                "date": date_str,
            })
            step += 1
            progress.progress(step / total_steps)

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

    with st.sidebar:
        st.subheader("Filters")
        company_filter = st.text_input("Company (optional)", placeholder="e.g. Comcast")
        doc_type_filter = st.selectbox(
            "Doc Type (optional)",
            options=["All"] + list(DOC_OPTIONS.keys()),
        )
        if st.button("Clear Chat"):
            st.session_state.messages = []
            st.rerun()

    filters = {}
    if company_filter:
        filters["company"] = slugify(company_filter)
    if doc_type_filter != "All":
        filters["doc_type"] = doc_type_filter

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


# ── Page: Analyze Video ───────────────────────────────────────────────────────
def page_analyze():
    from analyzer import analyze_video, get_mime, SUPPORTED_MIME

    st.header("Analyze Interview Video")
    st.caption(
        "Upload a recorded interview video. Gemini will watch the full video and generate "
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
                "gemini-2.0-flash",
                "gemini-2.5-flash-preview-05-20",
                "gemini-2.5-pro-preview-05-06",
            ],
            index=0,
            key="av_model",
            help="2.0 Flash: fastest & cheapest (~$0.05/30min). 2.5 Flash: better reasoning (~$0.07). 2.5 Pro: best quality (~$0.59).",
        )

    supported_exts = ", ".join(f".{e}" for e in SUPPORTED_MIME)
    video_file = st.file_uploader(
        f"Upload Interview Video ({supported_exts})",
        type=list(SUPPORTED_MIME.keys()),
        key="av_video",
    )

    if video_file:
        size_mb = video_file.size / 1_000_000
        st.info(f"📁 **{video_file.name}** — {size_mb:.0f} MB")

    ready = video_file is not None
    if st.button("Analyze Video", type="primary", disabled=not ready):
        gemini = get_gemini()
        status_box = st.empty()

        def update_status(msg):
            status_box.info(f"⏳ {msg}")

        try:
            video_bytes = video_file.read()
            report = analyze_video(
                client=gemini,
                video_bytes=video_bytes,
                filename=video_file.name,
                model=model_choice,
                status_callback=update_status,
            )

            status_box.success("Analysis complete!")

            # Build filename and save to disk
            date_str = datetime.now().strftime("%m-%d-%y")
            company_slug = slugify(company) if company else "unknown"
            video_stem = video_file.name.rsplit(".", 1)[0]
            filename = f"{date_str}_{company_slug}_{video_stem}_analysis.md"

            run_dir = BASE_OUTPUT_DIR / f"{date_str}_{company_slug}"
            run_dir.mkdir(parents=True, exist_ok=True)
            filepath = run_dir / filename
            filepath.write_text(report, encoding="utf-8")

            st.session_state.video_report = {
                "content": report,
                "filename": filename,
                "company": company_slug,
                "doc_type": "video_analysis",
                "date": date_str,
            }

        except Exception as e:
            status_box.error(f"Error: {e}")

    # Show report
    if st.session_state.get("video_report"):
        doc = st.session_state.video_report
        st.divider()

        col_dl, col_idx = st.columns([1, 1])
        with col_dl:
            st.download_button(
                label="Download Report (.md)",
                data=doc["content"],
                file_name=doc["filename"],
                mime="text/markdown",
                key="av_download",
            )
        with col_idx:
            if st.button("Index into Pinecone for Chat", key="av_index"):
                index = get_pinecone_index()
                gemini = get_gemini()
                meta = {
                    "company": doc["company"],
                    "doc_type": doc["doc_type"],
                    "date": doc["date"],
                }
                count = ingest_doc(index, gemini, doc["content"], meta)
                st.success(f"Indexed {count} chunks. You can now chat with this report in the Chat tab.")

        st.markdown(doc["content"])


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
