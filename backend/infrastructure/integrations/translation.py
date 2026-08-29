"""Azure Translator HTTP adapter."""

import os
import uuid
from typing import Any

import requests


key = os.getenv("AZURE_TRANSLATOR_KEY")
endpoint = os.getenv("AZURE_TRANSLATOR_ENDPOINT")
region = os.getenv("AZURE_TRANSLATOR_REGION")


def translate(text: str, target_language: str) -> Any:
    """Call Azure Translator with the legacy request shape and timeout."""

    endpoint_url = endpoint if endpoint.endswith("/") else f"{endpoint}/"
    url = f"{endpoint_url}translate"
    params = {"api-version": "3.0", "to": [target_language]}
    headers = {
        "Ocp-Apim-Subscription-Key": key,
        "Ocp-Apim-Subscription-Region": region,
        "Content-type": "application/json",
        "X-ClientTraceId": str(uuid.uuid4()),
    }
    proxy_url = (
        os.getenv("HTTP_PROXY")
        or os.getenv("HTTPS_PROXY")
        or os.getenv("ASW_PROXY_URL")
    )
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    request = requests.post(
        url,
        params=params,
        headers=headers,
        json=[{"text": text}],
        proxies=proxies,
        timeout=(30, 60),
    )
    request.raise_for_status()
    return request.json()
