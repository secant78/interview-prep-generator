# Interview Prep Generator

An AI-powered interview preparation tool built with Streamlit and Google Gemini. Generate personalized prep documents from your resume and job description, analyze recorded interview videos for detailed feedback, chat with all your prep materials using RAG, and browse all your documents from Google Drive.

---

## Features

### Generate Documents
Upload your resume and paste a job description to generate up to 6 tailored documents. All documents are saved locally, uploaded to Google Drive, and automatically indexed into Pinecone for chat.

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
15 role-specific questions across three sections, each with a complete model answer and a scoring rubric.

- **Section A (Q1–Q5):** Core technical area 1 from the JD
- **Section B (Q6–Q10):** Core technical areas 2 and 3 from the JD
- **Section C (Q11–Q15):** Migration scenarios, architecture decisions, and behavioral depth questions
- Each question includes a **full first-person model answer** (10-20 sentences), specific tool references, and a 1–5 scoring rubric
- Scoring table at the end maps every question to its topic, target score, and any AMBER notes from your resume

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
Upload a recorded interview video and get three AI-generated documents. Enter the interviewee and interviewer names so the transcript uses the correct labels. Uses a 4-call strategy:

- **Call 1 (video)** — Generates a timestamped transcript + analyzes everything visual: eye contact, body language, posture, hand gestures, facial expressions
- **Call 2 (text only)** — Analyzes the transcript for filler words, speech pace, answer quality, STAR method usage, and coding question extraction
- **Call 3 (text only)** — Combines both analyses into one unified final performance report with cross-references
- **Call 4 (text only)** — Extracts structured interview intelligence from the transcript

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

All three files are saved locally, uploaded to Google Drive, and automatically indexed into Pinecone so you can ask questions in the Chat tab (e.g. *"What questions did I struggle with?"*, *"What tools came up in the interview?"*).

**Tech Prep mode:** Upload a study session or tech prep video instead of an interview. Generates a transcript + study guide covering all concepts, questions, and narratives discussed — automatically indexed for chat.

**Company auto-detection:** If you leave the company field blank, Gemini detects the company from visual cues in the video (logos, screen content, email domains, interviewer intro) and uses it for the folder name.

### Document Library
Browse all your generated documents pulled directly from Google Drive. Supports search by filename, company, or doc type, and filter dropdowns for company and doc type. Documents are grouped by run folder. From the library you can:

- **Download** any document
- **Index** any document into Pinecone on demand

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

# Optional — enables hybrid mode (cuts video analysis cost ~10x)
GROQ_API_KEY=your_groq_api_key
DASHSCOPE_API_KEY=your_dashscope_api_key

# Optional — enables Google Drive document storage
GOOGLE_SERVICE_ACCOUNT_JSON=C:\path\to\service-account.json
GOOGLE_DRIVE_FOLDER_NAME=interview-prep
GOOGLE_DRIVE_FOLDER_ID=your_drive_folder_id
```

- **Gemini API key:** [aistudio.google.com](https://aistudio.google.com) — requires billing enabled for video analysis
- **Pinecone API key:** [pinecone.io](https://www.pinecone.io) — free tier is sufficient
- **Groq API key:** [console.groq.com](https://console.groq.com) — free tier, used for Whisper transcription
- **DashScope API key:** [dashscope.aliyuncs.com](https://dashscope.aliyuncs.com) — Qwen2.5-VL for visual analysis

### 4. (Optional) Set up Google Drive
Documents are automatically uploaded to Google Drive if configured. To enable:

1. Create a service account in [Google Cloud Console](https://console.cloud.google.com) and download the JSON key
2. Enable the **Google Drive API** on your project
3. Create a folder in your Google Drive and share it with the service account email (Editor access)
4. Copy the folder ID from the URL (`drive.google.com/drive/folders/<FOLDER_ID>`) and add it to `.env` as `GOOGLE_DRIVE_FOLDER_ID`

### 5. Run the app
```bash
streamlit run app.py
```

---

## Project Structure

```
interview-prep-generator/
├── app.py              # Streamlit UI — Generate, Analyze Video, Documents, Chat tabs
├── analyzer.py         # Video analysis logic (upload, transcript, visual + text analysis)
├── generators.py       # Document generation functions (one per doc type)
├── prompts.py          # All LLM prompts for document generation
├── ingest.py           # Pinecone ingestion utilities
├── drive.py            # Google Drive integration (upload, list, download)
├── requirements.txt    # Python dependencies
└── .streamlit/
    └── config.toml     # Streamlit config (2GB upload + message size limits)
```

---

## Video Analysis Modes

| Mode | Description |
|------|-------------|
| **Gemini-only** | Default. Sends video directly to Gemini for transcription and visual analysis. |
| **Hybrid (Qwen + Gemini)** | Add `DASHSCOPE_API_KEY`. Uses Qwen2.5-VL for visual analysis, Gemini for audio. |
| **Full hybrid (Qwen + Groq + Gemini)** | Add both keys. Groq Whisper handles transcription for free, cutting cost ~10x. |

---

## Cost Estimates

### Document Generation
Each document generation call uses Gemini 2.5 Flash on text only — costs fractions of a cent per document.

### Video Analysis (per 30-minute video)

| Model | Cost |
|-------|------|
| gemini-2.0-flash-lite | ~$0.03 |
| gemini-2.5-flash | ~$0.08 |
| gemini-2.5-pro | ~$1.25 |

The 4-call strategy sends the video only once (Call 1). Calls 2, 3, and 4 are cheap text-only calls on the transcript, cutting cost significantly vs. sending the video multiple times.

> **Note:** Gemini has a free tier but video analysis consumes a large number of tokens and will quickly exceed free limits. Enable billing on your Google Cloud project for uninterrupted use.

---

## Tech Stack

- **[Streamlit](https://streamlit.io)** — Web UI
- **[Google Gemini](https://ai.google.dev)** — LLM for generation, analysis, and embeddings
- **[Pinecone](https://www.pinecone.io)** — Vector database for RAG
- **[Google Drive API](https://developers.google.com/drive)** — Cloud document storage
- **[Groq](https://groq.com)** — Free Whisper transcription (optional)
- **[Qwen2.5-VL](https://dashscope.aliyuncs.com)** — Visual analysis via DashScope (optional)
- **[pypdf](https://pypdf.readthedocs.io)** — Resume PDF parsing
