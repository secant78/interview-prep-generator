# Interview Prep Generator

An AI-powered interview preparation tool built with Streamlit and Google Gemini. Generate personalized prep documents from your resume and job description, analyze recorded interview videos for detailed feedback, and chat with all your prep materials using RAG.

---

## Features

### Generate Documents
Upload your resume and paste a job description to generate up to 6 tailored documents:

| Document | Description |
|----------|-------------|
| **The Complete Story** | A "Faceless Man" narrative connecting your background to the role |
| **Interview Prep Playbook** | Gap analysis, STAR stories, and question-by-question strategy |
| **Mock Interview Q&A** | 15 likely questions with scored answer rubrics |
| **Profile Narratives** | STAR-formatted stories tailored to the target company |
| **Tools Narratives** | Per-tool answers for technical stack questions |
| **Company Research** | Real-time company research using Gemini + Google Search grounding |

All documents are saved as Markdown files and automatically indexed into Pinecone for chat.

### Analyze Video
Upload a recorded interview video and get a full AI-generated feedback report. Uses a cost-optimized 3-call strategy:

- **Call 1 (video)** — Generates a timestamped transcript + analyzes everything visual: eye contact, body language, posture, hand gestures, facial expressions
- **Call 2 (text only)** — Analyzes the transcript for filler words, speech pace, answer quality, STAR method usage, and coding question extraction
- **Call 3 (text only)** — Combines both analyses into one unified final report with cross-references

**The report includes:**
- Overall score and executive summary
- What you did well vs. what needs improvement (with timestamps)
- Scored breakdown: body language, eye contact, facial expressions, speech patterns, answer quality, overall presence
- Coding interview section (auto-detected): extracts the question, evaluates your solution, correctness, complexity, edge cases
- Top 5 priority improvements + concrete action plan

**The transcript includes:**
- Full word-for-word transcription
- `[HH:MM:SS]` timestamps per speaker turn and every ~30 seconds
- Filler words preserved for accuracy
- Speaker labels (names if audible, otherwise Interviewer/Candidate)

Both files are saved to disk and automatically indexed into Pinecone so you can ask timestamp-specific questions in the Chat tab (e.g. *"At what point did I lose confidence?"*).

**Company auto-detection:** If you leave the company field blank, Gemini detects the company from visual cues in the video (logos, screen content, email domains, interviewer intro) and uses it for the folder name.

### Chat
RAG-powered chat over all your generated and analyzed documents. Ask anything about your prep materials:

- *"How should I answer the 'tell me about yourself' question for this role?"*
- *"What were my biggest weaknesses in the interview?"*
- *"At what timestamp did I start rambling?"*
- *"What is the optimal solution to the coding question I was asked?"*

Filter by company or document type using the sidebar.

---

## Setup

### 1. Clone the repo
```bash
git clone https://github.com/secant78/interview-prep-generator.git
cd interview-prep-generator
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Set up API keys
Create a `.env` file in the project root:
```
GEMINI_API_KEY=your_gemini_api_key
PINECONE_API_KEY=your_pinecone_api_key
```

- **Gemini API key:** [aistudio.google.com](https://aistudio.google.com) — requires billing enabled for video analysis
- **Pinecone API key:** [pinecone.io](https://www.pinecone.io) — free tier is sufficient

### 4. Run the app
```bash
streamlit run app.py
```

---

## Project Structure

```
interview-prep-generator/
├── app.py              # Streamlit UI — Generate, Analyze Video, Chat tabs
├── analyzer.py         # Video analysis logic (upload, transcript, visual + text analysis)
├── generators.py       # Document generation functions (one per doc type)
├── prompts.py          # All LLM prompts for document generation
├── ingest.py           # Pinecone ingestion utilities
├── requirements.txt    # Python dependencies
└── .streamlit/
    └── config.toml     # Streamlit config (2GB upload + message size limits)
```

---

## Cost Estimates

### Document Generation
Each document generation call uses Gemini 2.5 Flash on text only — costs fractions of a cent per document.

### Video Analysis (per 30-minute video)

| Model | Cost |
|-------|------|
| gemini-2.0-flash | ~$0.05 |
| gemini-2.5-flash | ~$0.08 |
| gemini-2.5-pro | ~$1.25 |

The 3-call split strategy cuts cost ~50% vs. sending the video twice by replacing the second video call with a cheap text-only call on the transcript.

> **Note:** Gemini has a free tier but video analysis consumes a large number of tokens and will quickly exceed free limits. Enable billing on your Google Cloud project for uninterrupted use.

---

## Tech Stack

- **[Streamlit](https://streamlit.io)** — Web UI
- **[Google Gemini](https://ai.google.dev)** — LLM for generation, analysis, and embeddings
- **[Pinecone](https://www.pinecone.io)** — Vector database for RAG
- **[pypdf](https://pypdf.readthedocs.io)** — Resume PDF parsing
