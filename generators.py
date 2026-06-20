from google import genai
from google.genai import types
from prompts import (
    SYSTEM_BASE,
    STORY_DOC_PROMPT,
    PLAYBOOK_PROMPT,
    MOCK_QA_PROMPT,
    NARRATIVES_PROMPT,
    TOOLS_PROMPT,
    RESEARCH_PROMPT,
    TECH_PREP_PROMPT,
)

MODEL = "gemini-2.5-flash"


def _call(client: genai.Client, prompt: str):
    """Returns (text, response) so callers can extract usage_metadata."""
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_BASE,
            max_output_tokens=65535,
            temperature=0.7,
        ),
    )
    return response.text, response


def generate_story(client: genai.Client, resume: str, job_desc: str):
    return _call(client, STORY_DOC_PROMPT.format(resume=resume, job_desc=job_desc))


def generate_playbook(client: genai.Client, resume: str, job_desc: str):
    return _call(client, PLAYBOOK_PROMPT.format(resume=resume, job_desc=job_desc))


def generate_mock_qa(client: genai.Client, resume: str, job_desc: str):
    return _call(client, MOCK_QA_PROMPT.format(resume=resume, job_desc=job_desc))


def generate_narratives(client: genai.Client, resume: str, job_desc: str):
    return _call(client, NARRATIVES_PROMPT.format(resume=resume, job_desc=job_desc))


def generate_tools(client: genai.Client, resume: str, job_desc: str):
    return _call(client, TOOLS_PROMPT.format(resume=resume, job_desc=job_desc))


def generate_tech_prep(client: genai.Client, resume: str, job_desc: str, company: str, role: str):
    return _call(client, TECH_PREP_PROMPT.format(resume=resume, job_desc=job_desc, company=company, role=role))


def generate_research(client: genai.Client, company: str, role: str, job_desc: str):
    """Uses Gemini with Google Search grounding to research the company in real time."""
    prompt = RESEARCH_PROMPT.format(company=company, role=role, job_desc=job_desc)
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            max_output_tokens=65535,
            temperature=0.7,
            tools=[types.Tool(google_search=types.GoogleSearch())],
        ),
    )
    return response.text, response
