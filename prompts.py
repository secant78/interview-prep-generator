SYSTEM_BASE = """You are an expert career coach and technical interview strategist. Your job is to create deeply personalized, operationally specific interview preparation documents for software engineers and DevOps/cloud engineers. You write with confidence and specificity — no vague filler, no generic advice. Every story you craft is grounded in the candidate's actual resume and the target job description."""


# ---------------------------------------------------------------------------
# Document 1: The Faceless Story
# ---------------------------------------------------------------------------

STORY_DOC_PROMPT = """Using the resume and job description below, write THE COMPLETE STORY document — a narrative interview prep guide that positions the candidate as the ideal hire.

RESUME:
{resume}

JOB DESCRIPTION:
{job_desc}

---

CRITICAL FORMATTING RULES:
- Every section header must be on its own line with # ## or ###
- Every bullet point must start on its own line with -
- Always put a blank line before and after bullet lists and headers
- Never run separate items together on the same line
- Bold uses **double asterisks**

Generate a full markdown document following this EXACT structure. Be thorough, specific, and use details from the resume. Every story must reference real companies, real tools, and real outcomes from the resume.

# THE COMPLETE STORY
## A Faceless Man's Declaration

**[Candidate full name]**
*[Title from resume]*

| | |
|---|---|
| **Experience** | [Years of experience summary] |
| **Career Arc** | Company1 → Company2 → ... → Current |
| **Targeting** | [Company] — [Role Title] |
| **Prepared** | [Current month year] |

---

## How to Use This Document
[2-3 paragraphs explaining the strategic positioning for this specific role. Identify the 3-4 key requirements from the JD and map them directly to the candidate's experience. Call out any gaps and characterize them as narrow/manageable.]

---

## Chapter 1: The Arc

### Your 30-Second Pitch
[Write a 5-7 sentence pitch in first person. Mention years of experience, the 2-3 most relevant skills for this role, specific migration/platform work, and end with why this specific role is the right next step. Make it concrete — name tools, scale metrics, and outcomes.]

### Why Each Move Made Sense
[For each job transition in the resume, write a short paragraph explaining what the previous role gave the candidate and what the next role added. Format each transition exactly as shown below. Thread the narrative toward the target role.]

#### 🏢 PreviousCompany → NextCompany
*[Start year] — [End year]*

[3-4 sentences explaining what the previous role provided and what the move added. Be specific about skills, tools, and growth.]

[Repeat this exact format for every transition, with a blank line between each one.]

---

## Chapter [N]: [Company Name] — [Memorable Subtitle]
[Date range] | [Title] | [City, State]

### The Platform Challenge
[2-3 sentences setting the scene: what the company did, what the infrastructure challenge was, and why the stakes were high. This frames WHY the stories matter.]

### Story 1: [Descriptive Title]
[3-5 sentences explaining what you built/did, what the technical challenge was, and what the outcome was. Be specific: name the tools, the scale, the before/after.]

### Story 2: [Descriptive Title]
[Same format]

### Story 3: [Descriptive Title] (if applicable)
[Same format]

[Repeat Chapter N for each job in the resume, most recent first after Rackspace/earliest role]

---

## Chapter [Last]: The Knowledge Gaps — How to Frame Them

[For each AMBER/gap area identified from the JD vs resume, write a section:]
### Gap [N]: [Topic]
[How to frame it: write a first-person script the candidate can use verbatim. Start with what they DO have, acknowledge the gap honestly, then bridge to how they'd ramp quickly. 3-5 sentences.]

[Also include: "What you now know:" — a bullet list of specific technical facts about this gap area that the candidate should be able to recite if pressed.]

---

## Chapter [N+1]: Danger Questions

[For each of the 4-6 most likely hard questions for this specific role, write:]
### Q: [The question]
[A first-person answer the candidate can use. Be step-by-step for process questions. Be specific and operational. 8-15 sentences. Reference real stories from the resume where possible.]

---

## Chapter [N+2]: Before You Walk In
### Five Things They Will Remember About You

1. [The strongest differentiator — migration execution, platform work, etc. — stated as a bold claim with evidence from the resume.]

2. [Second differentiator — usually the observability/tooling depth.]

3. [Third differentiator — scale/team impact of the IaC or platform work.]

4. [Fourth differentiator — foundational depth (Linux, security, etc.)]

5. [Fifth differentiator — the security/compliance posture or unique angle.]

---

The Faceless Men would accept this story. Now make it yours.
End of Story Document     Prepared: [Month Year]"""


# ---------------------------------------------------------------------------
# Document 2: Interview Prep Playbook
# ---------------------------------------------------------------------------

PLAYBOOK_PROMPT = """Using the resume and job description below, write a full INTERVIEW PREP PLAYBOOK document.

RESUME:
{resume}

JOB DESCRIPTION:
{job_desc}

---

CRITICAL FORMATTING RULES — follow these exactly or the document will be unreadable:
- Every section header must be on its own line preceded by ## or ###
- Every bullet point must start on a new line with a dash (- )
- Every table must use proper markdown pipe syntax with a header separator row
- Never run separate items together on the same line
- Always put a blank line before and after tables, bullet lists, and headers
- Bold text uses **double asterisks** — never use single asterisks for bold
- Use --- on its own line to separate major sections

---

Generate the document using this EXACT structure and formatting:

# INTERVIEW PREP PLAYBOOK
## [Company Name] — [Role Title]
**Candidate:** [Full Name]
**Prepared:** [Month Year]

---

## Part 1: Gap Analysis

| Area | Level | Evidence | Bridge if Asked |
|------|-------|----------|-----------------|
| [Skill from JD] | GREEN | [Company — specific tool/project] | [One sentence bridge] |
| [Skill from JD] | AMBER | [Company — specific tool/project] | [One sentence bridge] |

Include 8-12 rows. Each row on its own line. Level must be GREEN, AMBER, or RED.

**Summary:** [3 sentences: count of GREEN/AMBER/RED, strongest differentiator, one area to prepare bridges for.]

---

## Part 2: Platform Stories

### Story 1: [Memorable Title]

**Role:** [Title at that company]

**Situation:** [1-2 sentences — what was broken or needed to change]

**Task:** [1 sentence — your specific objective]

**Action:**

- [Specific action with tool names]
- [Specific action with tool names]
- [Specific action with tool names]
- [Specific action with tool names]

**Result:** [2-3 sentences with concrete metrics — time saved, cost reduced, incidents eliminated]

**Hook:** "[One sentence connecting this story to what the target company needs]"

---

[Repeat Story 2 through Story 4-5 using the same format with a blank line between each field]

---

## Part 3: Technical Deep Dives

### [Technical Area 1 from JD]

**Core workflow:**

1. [Step one]
2. [Step two]
3. [Step three]

**Key components:**

- **[Component]:** [One-line explanation]
- **[Component]:** [One-line explanation]

**Common failure modes:**

- [Failure mode] → [Fix]
- [Failure mode] → [Fix]

**Why not the alternative:** [1-2 sentences]

---

[Repeat for 4-5 technical areas]

---

## Part 4: Red Flag Deflections

### "[Paraphrased objection the interviewer might raise]"

"[First-person response. 3-5 sentences. Lead with what you DO have, bridge to the gap, close with confidence.]"

---

[Repeat for each gap area]

---

## Part 5: Opening Statement

[Write 5-7 sentences in first person. Each sentence on its own line or as a flowing paragraph — do NOT use bullet points here.]

---

## Part 6: Questions to Ask the Interviewer

1. [Question that signals operational depth — references a specific challenge from the JD]
2. [Question]
3. [Question]
4. [Question]
5. [Question]
6. [Question]

---

## Part 7: Rapid-Reference Cheat Sheet

### Key Metrics

- [Company]: [Quantified outcome — numbers required]
- [Company]: [Quantified outcome]
- [Company]: [Quantified outcome]
- [Company]: [Quantified outcome]

### Story-to-Question Mapping

| If they ask about... | Use this story |
|----------------------|---------------|
| [Topic] | Story [N]: [Title] |
| [Topic] | Story [N]: [Title] |

### AMBER Area Quick Answers

**[AMBER skill]:** "[2-3 sentence bridge answer]"

**[AMBER skill]:** "[2-3 sentence bridge answer]"

---

End of Interview Prep Playbook     Prepared: [Month Year]"""


# ---------------------------------------------------------------------------
# Document 3: Mock Q&A
# ---------------------------------------------------------------------------

MOCK_QA_PROMPT = """Using the resume and job description below, write a MOCK INTERVIEW Q&A document with 15 questions.

RESUME:
{resume}

JOB DESCRIPTION:
{job_desc}

---

CRITICAL FORMATTING RULES:
- Every section header must be on its own line with ## or ###
- Every bullet point must start on its own line with -
- Always put a blank line before and after bullet lists, headers, and code blocks
- Never run separate items together on the same line
- Bold uses **double asterisks**
- Use --- on its own line between major sections

Generate a full markdown document following this EXACT structure:

# MOCK INTERVIEW Q&A
[Company] — [Role Title]
Format: Technical Interview | 15 Questions
Prepared: [Month Year]

---

## Interview Format
[3-4 bullet points describing what the role centers on, drawn from the JD]

Questions Q1–Q5 cover [core area 1] (core). Q6–Q10 cover [core area 2 and 3]. Q11–Q15 cover [scenarios and experience depth].

---

## SECTION A: [Core Area 1 from JD] (Core Knowledge)

[5 questions — Q1 through Q5. For each:]

### Q[N]. [The question — make it specific to this role, not generic]

**Strong answer:**

[1-2 sentence opening that directly answers the question in first person.]

**[Sub-topic or approach label]:**
[2-3 sentences of specific detail — name tools, company context, and outcome.]

**[Sub-topic or approach label]:**
[2-3 sentences of specific detail.]

**[Sub-topic or approach label]:**
[2-3 sentences of specific detail.]

[1-2 sentence closing that ties it together and connects to the target role.]

[Repeat this format for every question. Never write the answer as one long paragraph or use inline numbered lists (1. 2. 3.) — always use the bold label + paragraph structure above.]

---

## SECTION B: [Core Area 2 and 3 from JD] (Core Knowledge)

[5 questions — Q6 through Q10. Same format as Section A.]

---

## SECTION C: Migration Scenarios & Experience Depth

[5 questions — Q11 through Q15. Include at least one "tell me about a time" question, one multi-tier architecture scenario, one network troubleshooting scenario, and one decision-framework question. Same format.]

---

End of Mock Interview Q&A     Prepared: [Month Year]"""


# ---------------------------------------------------------------------------
# Document 4: Profile Narratives (STAR per company)
# ---------------------------------------------------------------------------

NARRATIVES_PROMPT = """Using the resume and job description below, write PROFILE NARRATIVES — STAR-format stories for each company, optimized for the target role.

RESUME:
{resume}

JOB DESCRIPTION:
{job_desc}

---

For each job in the resume (most recent 3-4 companies), write a STAR narrative following this format:

## [Company Name]: **[Memorable Subtitle — what the main achievement was]**

**Situation:** [2-3 sentences. What was the state of the infrastructure/platform when you arrived or when the project started? What was the business problem or risk?]

**Task:** [1-2 sentences. What was your specific objective or responsibility?]

**Action:**

- **[Descriptive Sub-heading]:** [3-4 sentences explaining one major action you took. Name the specific tools, services, and design decisions. Be technical.]
- **[Descriptive Sub-heading]:** [Same]
- **[Descriptive Sub-heading]:** [Same]
- **[Descriptive Sub-heading]:** [Same — include 3-4 action bullets per story]

**Result:** [2-3 sentences. Quantified outcomes: percentage improvements, time saved, cost reduced, scale achieved, compliance passed, incidents eliminated. Connect back to the business impact.]

[Repeat for each of the 3-4 most recent/relevant companies. Focus on the stories most relevant to the target JD.]"""


# ---------------------------------------------------------------------------
# Document 5: Tools Narratives
# ---------------------------------------------------------------------------

TOOLS_PROMPT = """Using the resume and job description below, write TOOLS NARRATIVES — specific, first-person answers for each major tool or technology listed in the JD.

RESUME:
{resume}

JOB DESCRIPTION:
{job_desc}

---

For each major tool/technology required by the JD, write a first-person narrative answer. These are what you would say if asked "Tell me about your experience with [tool]." Format as:

### [Tool Name]:

[3-5 sentences in first person. Include: which company you used it at, what you specifically built or operated with it, the scale or complexity of the work, and one specific technical detail that shows depth. Do NOT be generic. Every sentence should be falsifiable — meaning it references a real decision, real scale, or real outcome from the resume.]

---

Cover all tools listed in the JD skills/requirements section. For tools where the resume shows strong evidence, write 5-6 sentences with depth. For AMBER tools (present but not deep), write 3-4 sentences and include an honest bridge: acknowledge the depth is developing while leading with what you DO have.

After all tool narratives, add a section:

## Monitoring & Observability

[Write the monitoring narrative as a response to "What monitoring tools have you used?" — name all the monitoring/observability tools from the resume with specific context for each.]

## If Asked About [Gap Tool from JD]:

[For any tool in the JD that is NOT on the resume but is listed as required or preferred, write an honest bridge answer. Lead with the closest analog you have, explain the transferability, and note you'd ramp quickly.]"""


# ---------------------------------------------------------------------------
# Document 6: Company Research
# ---------------------------------------------------------------------------

RESEARCH_PROMPT = """You are a technical recruiter and engineering intelligence analyst. Using your Google Search grounding, research the following company and role, then produce a comprehensive Company Intelligence Report that a job candidate can study before their interview.

COMPANY: {company}
ROLE: {role}

JOB DESCRIPTION:
{job_desc}

---

Search for and compile the most current, accurate information available. Be specific — name actual products, services, tools, and recent announcements. Do not generalize. If you find conflicting information, note it.

Generate a full markdown document following this EXACT structure:

# Company Intelligence Report
## {company} — {role}
Prepared: [Current Month Year]
*Sources gathered via live web search*

---

## 1. Company Overview
- **Industry & Business Model:** [What they do, how they make money, who their customers are]
- **Scale:** [Employee count, revenue if public, number of customers/subscribers]
- **Engineering Organization:** [Estimated engineering headcount, key engineering locations, notable engineering leaders]
- **Public/Private:** [Stock ticker if public, valuation if private]
- **Recent Business Context:** [Any mergers, acquisitions, restructuring, layoffs, or major strategic shifts in the last 12 months]

---

## 2. Cloud & Infrastructure
- **Primary Cloud Provider(s):** [AWS / Azure / GCP — which ones and what they use each for]
- **Multi-Cloud or Hybrid:** [Yes/no and what that looks like in practice]
- **Data Centers:** [Own data centers, colocation, or fully cloud — locations if known]
- **Known Cloud Services Used:** [Specific services: EC2, EKS, RDS, S3, Azure AKS, GCP GKE, etc.]
- **Scale Indicators:** [Any public data on traffic volume, data processed, uptime requirements]

---

## 3. Tech Stack
- **Primary Languages:** [Languages used across engineering — with context on which teams use what]
- **Frameworks & Runtimes:** [Web frameworks, API frameworks, data processing runtimes]
- **Databases:** [Relational, NoSQL, caching, data warehouse — specific products]
- **Messaging & Streaming:** [Kafka, Kinesis, RabbitMQ, SQS, etc.]
- **Networking & CDN:** [Load balancers, CDN providers, DNS, edge infrastructure]
- **Internal Developer Platform:** [Any known internal platforms or developer portals]

---

## 4. DevOps & Platform Engineering
- **Container Orchestration:** [Kubernetes flavor — EKS, AKS, GKE, OpenShift, self-managed — and scale]
- **CI/CD Tooling:** [Jenkins, GitHub Actions, GitLab CI, Argo CD, Spinnaker, etc.]
- **Infrastructure as Code:** [Terraform, Pulumi, CloudFormation, Ansible — what they use and how]
- **Observability Stack:** [Monitoring, logging, tracing tools — Datadog, Splunk, ELK, Prometheus, etc.]
- **Security Practices:** [Known DevSecOps tooling, compliance requirements, zero-trust initiatives]
- **Deployment Practices:** [Canary, blue/green, feature flags, release cadence]

---

## 5. Recent Tech Initiatives (Last 12 Months)
[For each initiative, write 3-4 sentences: what they announced or launched, why it matters, and what it signals about where their engineering is heading. Find at least 4-6 distinct initiatives.]

### [Initiative Title]
[Details]

### [Initiative Title]
[Details]

[Continue for all found initiatives]

---

## 6. Engineering Culture & Signals
- **Engineering Blog:** [URL if exists, recent post topics]
- **Open Source:** [Any notable open source projects or contributions]
- **Tech Talks & Conferences:** [Recent conference presentations by their engineers]
- **Hiring Signals:** [What their current job postings reveal about tech direction — beyond this role]
- **Glassdoor / Blind Intel:** [Interview process notes, common technical topics reported by candidates]

---

## 7. The Role in Context
- **Why This Role Exists Now:** [Based on your research, why is the company hiring for this specific role at this time — migration program, growth, replacing legacy systems, new initiative]
- **Team This Role Likely Sits On:** [Platform engineering, SRE, DevOps center of excellence, embedded in a product team, etc.]
- **What Success Looks Like:** [Based on the JD and company context, what will this person be doing in the first 90 days]

---

## 8. How to Tailor Your Answers
[This is the most important section. For each major technical area in the JD, write 2-3 sentences connecting what you found about the company's actual stack to how the candidate should frame their experience. Be specific — "They use EKS at scale, so lead with your EKS node group and IRSA work, not just generic Kubernetes."]

### [Technical Area 1]
[Tailoring advice]

### [Technical Area 2]
[Tailoring advice]

[Continue for 5-7 technical areas]

---

## 9. Smart Questions to Ask
[Based on your research, write 6-8 genuinely intelligent questions the candidate can ask the interviewer. Each question should reference something specific you found — a recent initiative, a known tech decision, a reported challenge. Not generic "what does success look like" questions.]

1. [Question referencing a specific finding]
2. [Question referencing a specific finding]
[Continue]

---

End of Company Intelligence Report     Prepared: [Month Year]"""


# ---------------------------------------------------------------------------
# Document 7: Tech Prep Study Guide
# ---------------------------------------------------------------------------

TECH_PREP_PROMPT = """Using the resume and job description below, write a TECH PREP STUDY GUIDE — a structured interview coaching document that predicts the technical questions the interviewer will ask, provides recommended answers the candidate can use verbatim, and identifies the concepts and stories they need to master.

RESUME:
{resume}

JOB DESCRIPTION:
{job_desc}

COMPANY: {company}
ROLE: {role}

---

CRITICAL FORMATTING RULES:
- Every section header must be on its own line with # ## or ###
- Every bullet point must start on its own line with -
- Always put a blank line before and after bullet lists and headers
- Never run separate items together on the same line
- Bold uses **double asterisks**
- Use --- on its own line between major sections

Generate the full document following this EXACT structure:

# Tech Prep Study Guide
**Company:** {company}
**Role:** {role}
**Candidate:** [Full name from resume]
**Prepared:** [Current month and year]

---

## Job Description
{job_desc}

---

## Session Overview
[3-4 sentences summarizing what this role demands technically, what the candidate's strongest relevant experience is, and what areas need the most preparation. Be specific — name the technologies, the gaps, and the focus areas.]

---

## Technical Questions Covered

[Generate 10-15 technical questions that are highly likely to be asked for this specific role based on the JD. For EACH question follow this exact format:]

### Q: "[The interview question — make it specific to this role and company context, not generic]"

**Recommended Answer:**
"[Write a complete, first-person answer the candidate can rehearse and use verbatim. 6-12 sentences. Reference the candidate's actual experience from the resume where relevant — name real companies, real tools, real outcomes. Be specific and operational. No filler phrases like 'great question' or 'I believe'.]"

**Key points to hit:**
- [Critical sub-point the answer must include]
- [Critical sub-point]
- [Critical sub-point]
- [Critical sub-point]

---

[Repeat for all 10-15 questions. Group behavioural questions at the end.]

---

## Technical Concepts to Master

[For each major technical concept required by the JD, write an entry. Include concepts the candidate shows on their resume AND concepts from the JD they may need to brush up on. For each:]

### [Concept Name]
**What it is:** [1-2 sentence definition — clear and plain English]
**Why it matters for this interview:** [1-2 sentences connecting it to this specific role and JD]
**What you should be able to say about it:**
- [Specific talking point grounded in their resume experience, or what to study if it's a gap]
- [Specific talking point]
- [Specific talking point]
**Depth required:** [One of: Surface / Working knowledge / Deep dive]

---

[Cover 8-15 concepts. Prioritize the ones that appear most prominently in the JD.]

---

## Stories & Narratives to Prepare

[Generate 3-5 STAR-format story prompts the candidate should prepare, drawn from their resume and tailored to what this role will likely ask about. For each:]

### Story: "[Memorable title for this story]"
**Answers this question type:** "[The kind of question this story answers — e.g. 'Tell me about a time you...' or 'Walk me through how you...']"
**Situation:** [1-2 sentences — what was the context or problem from their actual resume experience]
**Task:** [1 sentence — their specific responsibility]
**Action:** [3-5 bullet points — specific technical actions they took, naming real tools and decisions]
**Result:** [1-2 sentences — quantified outcome where possible]
**From the resume:** [Point to the specific job/project this story should draw from]

---

## Topics to Study Deeper

[Identify 3-5 areas where the JD requires expertise that appears limited or absent on the resume. For each:]

### [Topic]
**Why it came up:** [1 sentence explaining why this topic matters for this specific role]
**What to study:**
- [Specific sub-topic or concept to learn]
- [Specific sub-topic]
- [Specific sub-topic]
**Target depth:** [One of: Be able to define it / Be able to explain the architecture / Be able to walk through an implementation]

---

## Action Items Before the Interview

[Numbered list of 5-8 concrete, prioritized tasks the candidate should complete before the interview. Be specific — not "review Kubernetes" but "Review how HPA works and be able to explain the difference between CPU-based and custom-metric scaling."]

1. [Specific action item]
2. [Specific action item]
[Continue...]

---

## Key Phrases & Talking Points

[5-8 specific phrases or framings the candidate should use in their answers for this role. These are the lines that will make them sound senior and prepared. Quote them directly in quotes.]

- "[Phrase or talking point]"
- "[Phrase or talking point]"
[Continue...]

---

*Generated by Interview Prep Generator — Tech Prep Study Guide*
*{company} | {role} | [Current Month Year]*"""
