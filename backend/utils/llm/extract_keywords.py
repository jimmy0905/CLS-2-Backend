from openai import AzureOpenAI, DefaultHttpxClient
import os
import json
from fastapi.concurrency import run_in_threadpool
from utils.llm.text_cleaning_helper import _clean_response_content
from dotenv import load_dotenv
import httpx


load_dotenv()

client = AzureOpenAI(
    api_key=os.getenv(
        "AZURE_OPENAI_API_KEY",
        "",
    ),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-07-01-preview"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
    http_client=(
        DefaultHttpxClient(
            proxy=os.getenv("ASW_PROXY_URL"),
            transport=httpx.HTTPTransport(local_address="0.0.0.0"),
        )
        if os.getenv("ASW_PROXY_URL")
        else None
    ),
)

# Configs for extract keywords
EXTRACT_KEYWORDS_MODEL = os.getenv(
    "EXTRACT_KEYWORDS_MODEL", "gpt-4.1-mini-CLS-DataUpload"
)
EXTRACT_KEYWORDS_TEMPERATURE = float(os.getenv("EXTRACT_KEYWORDS_TEMPERATURE", 0.0))


def _extract_keywords_sync(text: str) -> tuple[list[str], dict]:
    system_prompt = """You are an AI assistant specialized in analyzing retail customer feedback. Your task is to extract 1 to 3 most important keywords from the comments. These keywords should focus on areas such as product quality, IT, customer service, pricing, and overall shopping experience or anything related to retails."""
    user_prompt = f"""Extract 1 to 3 most important keywords from the following customer comment. Make sure the words should be exactly the same as in the comment. Output only JSON with key \"keywords\":\n\n"{text}"\n"""

    response = client.chat.completions.create(
        model=EXTRACT_KEYWORDS_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=EXTRACT_KEYWORDS_TEMPERATURE,
    )
    response_content = response.choices[0].message.content
    if response_content is None:
        return [], None
    try:
        cleaned_response_content = _clean_response_content(response_content)
        return (
            json.loads(cleaned_response_content)["keywords"],
            response.usage.model_dump(),
        )
    except Exception as e:
        print(f"Error validating JSON response: {e}")
        print(f"Response content (first 500 chars): {response_content[:500]}")
        raise Exception(f"Failed to validate keywords response: {e}")


async def extract_keywords(text: str) -> tuple[list[str], dict]:
    return await run_in_threadpool(_extract_keywords_sync, text)
