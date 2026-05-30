from google import genai
from google.genai import types
from prompts import (
    SYSTEM_BASE,
    STORY_DOC_PROMPT,
    PLAYBOOK_PROMPT,
    MOCK_QA_PROMPT,
    NARRATIVES_PROMPT,
    TOOLS_PROMPT,
)

MODEL = "gemini-2.5-flash"


def _call(client: genai.Client, prompt: str) -> str:
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_BASE,
            max_output_tokens=65535,
            temperature=0.7,
        ),
    )
    return response.text


def generate_story(client: genai.Client, resume: str, job_desc: str) -> str:
    return _call(client, STORY_DOC_PROMPT.format(resume=resume, job_desc=job_desc))


def generate_playbook(client: genai.Client, resume: str, job_desc: str) -> str:
    return _call(client, PLAYBOOK_PROMPT.format(resume=resume, job_desc=job_desc))


def generate_mock_qa(client: genai.Client, resume: str, job_desc: str) -> str:
    return _call(client, MOCK_QA_PROMPT.format(resume=resume, job_desc=job_desc))


def generate_narratives(client: genai.Client, resume: str, job_desc: str) -> str:
    return _call(client, NARRATIVES_PROMPT.format(resume=resume, job_desc=job_desc))


def generate_tools(client: genai.Client, resume: str, job_desc: str) -> str:
    return _call(client, TOOLS_PROMPT.format(resume=resume, job_desc=job_desc))
