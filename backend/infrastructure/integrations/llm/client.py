import os
from functools import lru_cache

import httpx
from dotenv import load_dotenv
from openai import AzureOpenAI, DefaultHttpxClient


load_dotenv()


class LLMConfigurationError(RuntimeError):
    """Raised when an LLM operation is requested without Azure OpenAI settings."""


@lru_cache(maxsize=1)
def get_azure_openai_client() -> AzureOpenAI:
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    if not api_key or not endpoint:
        raise LLMConfigurationError(
            "Azure OpenAI is not configured. Set AZURE_OPENAI_API_KEY and "
            "AZURE_OPENAI_ENDPOINT before using LLM endpoints."
        )

    proxy_url = os.getenv("ASW_PROXY_URL")
    return AzureOpenAI(
        api_key=api_key,
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-07-01-preview"),
        azure_endpoint=endpoint,
        http_client=(
            DefaultHttpxClient(
                proxy=proxy_url,
                transport=httpx.HTTPTransport(local_address="0.0.0.0"),
            )
            if proxy_url
            else None
        ),
    )

