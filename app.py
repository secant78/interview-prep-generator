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
EMBEDDING_MODEL = "text-embedding-004"
EMBEDDING_DIM = 768
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
    existing = [i.name for i in pc.list_indexes()]
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


def ingest_doc(index, gemini_client, text: str, meta: dict) -> int:
    chunks = chunk_markdown(text, meta)
    if not chunks:
        return 0
    texts = [c["text"] for c in chunks]
    result = gemini_client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=texts,
        config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
    )
    embeddings = [e.values for e in result.embeddings]
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

        progress = st.progress(0)
        status = st.empty()

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
            progress.progress((i + 1) / len(doc_keys))

        status.text("Done!")
        st.success(f"Generated {len(doc_keys)} document(s). Saved to: {run_dir}")

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

        st.divider()
        st.subheader("Index Documents for Chat")
        st.caption("Indexes all generated documents into Pinecone so you can query them in the Chat tab.")

        if st.button("Index into Pinecone", type="secondary"):
            index = get_pinecone_index()
            gemini = get_gemini()
            total = 0
            progress = st.progress(0)
            docs = list(st.session_state.generated_docs.values())
            for i, doc in enumerate(docs):
                meta = {
                    "company": doc["company"],
                    "doc_type": doc["doc_type"],
                    "date": doc["date"],
                }
                count = ingest_doc(index, gemini, doc["content"], meta)
                total += count
                progress.progress((i + 1) / len(docs))
            st.success(f"Indexed {total} chunks into Pinecone.")


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


# ── App Shell ─────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Interview Prep Generator",
    page_icon="🎯",
    layout="wide",
)

st.title("Interview Prep Generator")

tab1, tab2 = st.tabs(["Generate Documents", "Chat"])

with tab1:
    page_generate()

with tab2:
    page_chat()
