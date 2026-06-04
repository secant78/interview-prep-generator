# Interview Prep Generator

An AI-powered interview preparation tool built with Streamlit and Google Gemini. Generate personalized prep documents from your resume and job description, analyze recorded interview videos for detailed feedback, chat with all your prep materials using RAG, and browse your document library.

---

## Features

### Generate Documents
Upload your resume and paste a job description to generate up to 6 tailored documents. All documents are saved locally and automatically indexed into Pinecone for chat.

---

#### 1. The Complete Story
A first-person narrative that positions you as the ideal hire for the specific role. Structured as chapters, one per employer.

- **30-second pitch** — concrete, role-specific, names tools and scale metrics
- **Career arc** — explains every job transition and threads the narrative toward the target role
- **Per-company chapters** — 2-3 stories per employer framing the platform challenge and your specific contribution
- **Gap handling** — for each AMBER/RED skill from the JD, a verbatim script to acknowledge and bridge it confidently
- **Danger questions** — full first-person answers to the 4-6 hardest questions for this specific role
- **Five things they'll remember about you** — your top differentiators stated as bold claims with resume evidence

---

#### 2. Interview Prep Playbook
A structured prep guide organized into 7 parts.

- **Gap analysis table** — every key skill from the JD rated GREEN / AMBER / RED with evidence and a one-sentence bridge
- **STAR stories** — 4-5 platform stories in full Situation / Task / Action / Result format with quantified outcomes and a hook connecting each story to the target company
- **Technical deep dives** — core workflow, key components, common failure modes, and "why not the alternative" for each major technical area in the JD
- **Red flag deflections** — first-person responses to likely objections about resume gaps
- **Opening statement** — a ready-to-use 5-7 sentence intro
- **Questions to ask the interviewer** — 6 questions that signal operational depth
- **Rapid-reference cheat sheet** — key metrics, story-to-question mapping table, and AMBER quick answers

---

#### 3. Mock Interview Q&A
15 role-specific questions across three sections, each with a complete model answer.

- **Section A (Q1–Q5):** Core technical area 1 from the JD
- **Section B (Q6–Q10):** Core technical areas 2 and 3 from the JD
- **Section C (Q11–Q15):** Migration scenarios, architecture decisions, and behavioral depth questions
- Each question includes a **full first-person model answer** (10-20 sentences) with bold sub-topic labels and specific tool references

---

#### 4. Profile Narratives
Deep STAR-format stories for each of your most recent 3-4 employers, written specifically for the target role.

- One story per employer covering the most relevant project or initiative
- **Action section** uses 3-4 descriptive sub-headings with specific tools, services, and design decisions
- **Result section** includes quantified outcomes — percentages, time saved, cost reduced, scale achieved
- Ordered and emphasized to match what the JD asks for most

---

#### 5. Tools Narratives
First-person "tell me about your experience with X" answers for every major tool and technology in the JD.

- **Strong tools** — 5-6 sentences naming the company, what you built, scale/complexity, and a specific technical detail that shows depth
- **AMBER tools** — 3-4 sentences leading with what you have, then an honest bridge acknowledging the gap
- **Gap tools** (required by JD but not on resume) — bridge answers leading with the closest analog and explaining transferability
- Closes with a **Monitoring & Observability** narrative covering all observability tools from the resume in one cohesive answer

---

#### 6. Company Research
A live-researched Company Intelligence Report generated using Gemini with Google Search grounding — no stale training data.

- **Company overview** — business model, scale, engineering org size, recent strategic shifts
- **Cloud & infrastructure** — primary cloud providers, specific services used, scale indicators
- **Tech stack** — languages, frameworks, databases, messaging, CDN, internal developer platform
- **DevOps & platform** — container orchestration, CI/CD tooling, IaC, observability stack, deployment practices, security posture
- **Recent tech initiatives** — 4-6 specific announcements or launches from the last 12 months and what they signal
- **Engineering culture** — blog, open source, conference talks, Glassdoor/Blind interview intel
- **Role in context** — why this role exists now, what team it sits on, what the first 90 days look like
- **How to tailor your answers** — per-topic coaching connecting the company's actual stack to your experience
- **Smart questions to ask** — 6-8 questions referencing specific findings from the research

### Analyze Video
Upload a recorded interview video and get three AI-generated documents. Uses a frame-based analysis strategy — no full video upload required:

- **Call 1 (frames)** — Extracts 1 JPEG frame every 10 seconds and sends them to Gemini as inline images for visual analysis: body language, posture, facial expressions, engagement level
- **Call 2 (audio)** — Transcribes audio via Groq Whisper (free) or Gemini audio fallback
- **Call 3 (text)** — Analyzes transcript for filler words, speech pace, answer quality, STAR usage, coding question extraction
- **Call 4 (text)** — Combines visual + text analyses into a unified performance report
- **Call 5 (text)** — Extracts structured interview intelligence from the transcript

**Performance Report includes:**
- Overall score and executive summary
- What you did well vs. what needs improvement (with timestamps)
- Scored breakdown: body language, eye contact, facial expressions, speech patterns, answer quality, overall presence
- Coding interview section (auto-detected): extracts the question, evaluates your solution, correctness, complexity, edge cases
- Top 5 priority improvements + concrete action plan

**Interview Intelligence document includes:**
- Detailed interview summary (6-10 sentences covering the full conversation)
- Every question asked — exact wording, timestamp, type, answer summary, and direct quote
- All tools & technologies mentioned, organized by category (Cloud, CI/CD, Containers, Languages, DBs, Monitoring, Security)
- Technical concepts and architectural topics discussed
- Key stories and examples the interviewee used, with source company context
- Topics NOT covered — prep gaps to address before future rounds
- Interviewer signals — what they seemed to care about most

**Transcript includes:**
- Full word-for-word transcription with correct speaker names
- `[HH:MM:SS]` timestamps per speaker turn and every ~30 seconds
- Filler words preserved for accuracy

All three files are saved locally and automatically indexed into Pinecone so you can ask questions in the Chat tab.

**Tech Prep mode:** Upload a study session or tech prep video instead of an interview. Generates a transcript + study guide covering all concepts, questions, and narratives discussed — automatically indexed for chat.

**Company auto-detection:** If you leave the company field blank, Gemini detects the company from visual cues in the video (logos, screen content, email domains, interviewer intro) and uses it for the folder name.

**API cost display:** After every video analysis or document generation run, a collapsible cost summary shows the exact token usage and dollar cost per API call.

### Document Library
Browse all your generated documents from your local documents folder. Supports search by filename, company, or doc type, and filter dropdowns for company and doc type. Documents are grouped by run folder. From the library you can:

- **Download** any document
- **Index** any document into Pinecone on demand
- See a **✅ badge** next to documents already indexed in Pinecone
- **Change the documents folder** via the 📂 Directory expander — saved to `.app_config.json` and persists across sessions

### Chat
RAG-powered chat over all your generated and analyzed documents. Ask anything about your prep materials:

- *"How should I answer the 'tell me about yourself' question for this role?"*
- *"What were my biggest weaknesses in the interview?"*
- *"At what timestamp did I start rambling?"*
- *"What is the optimal solution to the coding question I was asked?"*

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

# Optional — free Whisper transcription (recommended)
GROQ_API_KEY=your_groq_api_key
```

- **Gemini API key:** [aistudio.google.com](https://aistudio.google.com) — requires billing enabled for video analysis
- **Pinecone API key:** [pinecone.io](https://www.pinecone.io) — free tier is sufficient
- **Groq API key:** [console.groq.com](https://console.groq.com) — free tier, used for Whisper transcription

### 4. Run the app
```bash
streamlit run app.py
```

---

## Project Structure

```
interview-prep-generator/
├── app.py              # Streamlit UI — Generate, Analyze Video, Documents, Chat tabs
├── analyzer.py         # Video analysis logic (frame extraction, transcript, visual + text analysis)
├── generators.py       # Document generation functions (one per doc type)
├── prompts.py          # All LLM prompts for document generation
├── ingest.py           # Pinecone ingestion utilities
├── cost_tracker.py     # API token + cost tracking across all calls
├── drive.py            # Google Drive integration (kept for reference)
├── requirements.txt    # Python dependencies
└── .streamlit/
    └── config.toml     # Streamlit config (2GB upload + message size limits, minimal toolbar)
```

---

## Video Analysis

### How it works
Instead of uploading the full video file, the app extracts 1 JPEG frame every 10 seconds and sends them to Gemini as inline images. This keeps visual analysis cost nearly flat regardless of video length.

| Duration | Frames sent | Visual cost |
|----------|-------------|-------------|
| 30 min | ~180 frames | ~$0.007 |
| 60 min | ~360 frames | ~$0.014 |

Transcription uses Groq Whisper (free) if `GROQ_API_KEY` is set, otherwise falls back to Gemini audio upload.

### Cost by model (per 60-minute video)

| Model | Cost | Best For |
|-------|------|----------|
| gemini-2.0-flash-lite | ~$0.01 | Quick, cheap feedback |
| gemini-2.5-flash ⭐ | ~$0.02–0.04 | Best value — recommended |
| gemini-2.5-pro | ~$0.05–0.10 | Highest quality |

> Costs are shown live in the app after each run via the 💰 API Cost expander.

---

## Cost Estimates

### Document Generation
Each document uses Gemini 2.5 Flash on text only — fractions of a cent per document (~$0.01 for all 6).

### Video Analysis
~$0.02–0.04 per 60-minute video with Gemini 2.5 Flash + Groq Whisper. The frame-based approach is ~4-8x cheaper than sending the full video.

---

## Tech Stack

- **[Streamlit](https://streamlit.io)** — Web UI with background threading for non-blocking video analysis
- **[Google Gemini](https://ai.google.dev)** — LLM for generation, frame-based visual analysis, and RAG answers
- **[Pinecone](https://www.pinecone.io)** — Vector database with integrated `multilingual-e5-large` embeddings
- **[Groq](https://groq.com)** — Free Whisper transcription (optional)
- **[pypdf](https://pypdf.readthedocs.io)** — Resume PDF parsing
