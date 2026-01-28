from fastapi import APIRouter, Depends, HTTPException
from utils.database import get_db
from utils.security import get_current_user
from pydantic import BaseModel
from azure.ai.translation.text.models import InputTextItem
from models.User import User
import os
from azure.ai.translation.text import TextTranslationClient, TranslatorCredential
import uuid
import httpx

key = os.getenv("AZURE_TRANSLATOR_KEY")
endpoint = os.getenv("AZURE_TRANSLATOR_ENDPOINT")
region = os.getenv("AZURE_TRANSLATOR_REGION")

router = APIRouter(
    prefix="/translator",
    tags=["translator"],
    dependencies=[Depends(get_db), Depends(get_current_user)],
)


class DetectedLanguage(BaseModel):
    language: str
    score: float


class Translation(BaseModel):
    text: str
    to: str


class TranslationResponse(BaseModel):
    detected_language: DetectedLanguage
    translations: list[Translation]


class TranslationRequest(BaseModel):
    text: str
    target_language: str


@router.post("/translate")
async def translate(
    translation_request: TranslationRequest,
    current_user: User = Depends(get_current_user),
) -> TranslationResponse:
    url = f"{endpoint}translate"
    params = {
        'api-version': '3.0',
        'to': [translation_request.target_language]
    }

    headers = {
        'Ocp-Apim-Subscription-Key': key,
        'Ocp-Apim-Subscription-Region': region,
        'Content-type': 'application/json',
        'X-ClientTraceId': str(uuid.uuid4())
    }
    body = [{
    'text': translation_request.text
    }]

    proxy_url = os.getenv("ASW_PROXY_URL")
    
    # Configure timeout (30 seconds for connect, 60 seconds for read)
    timeout = httpx.Timeout(30.0, read=60.0)
    
    # Configure client based on proxy availability
    client_kwargs = {
        "verify": False,
        "timeout": timeout,
    }
    
    if proxy_url:
        # Use proxy parameter for httpx (singular, not plural)
        client_kwargs["proxy"] = proxy_url
        print(f"Using proxy: {proxy_url}")
    
    async with httpx.AsyncClient(**client_kwargs) as client:
        try:
            print(f"Sending request to {url} with params {params}, headers {headers}, and body {body}")
            request = await client.post(url, params=params, headers=headers, json=body)
            request.raise_for_status()
        except httpx.TimeoutException as e:
            print(f"Request timeout: {e}")
            raise HTTPException(status_code=504, detail="Translation service timeout")
        except httpx.ProxyError as e:
            print(f"Proxy error: {e}")
            raise HTTPException(status_code=502, detail=f"Proxy error: {str(e)}")
        except httpx.HTTPError as e:
            print(f"HTTP Request failed: {e}")
            raise HTTPException(status_code=500, detail=f"Translation service error: {str(e)}")
    
    response = request.json()

    if isinstance(response, list) and len(response) > 0:
        first_result = response[0]
        return TranslationResponse(
            detected_language=DetectedLanguage(
                language=first_result['detectedLanguage']['language'],
                score=first_result['detectedLanguage']['score'],
            ),
            translations=[
                Translation(
                    text=translation['text'],
                    to=translation['to'],
                )
                for translation in first_result['translations']
            ],
        )
    else:
        # Handle error or empty response
        print(f"Unexpected response format: {response}")
        raise HTTPException(status_code=400, detail="Translation failed or unexpected response")