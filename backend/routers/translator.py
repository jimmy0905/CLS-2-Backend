from fastapi import APIRouter, Depends, HTTPException
from utils.database import get_db
from utils.security import get_current_user
from pydantic import BaseModel
from models.User import User
import os
import uuid
import requests
import asyncio
from utils.logger import logger

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
    def make_translation_request():
        # Ensure endpoint ends with / for proper URL construction
        endpoint_url = endpoint if endpoint.endswith('/') else f"{endpoint}/"
        url = f"{endpoint_url}translate"
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

        # Check for proxy configuration
        proxy_url = os.getenv('HTTP_PROXY') or os.getenv('HTTPS_PROXY') or os.getenv('ASW_PROXY_URL')
        
        proxies = None
        if proxy_url:
            proxies = {
                'http': proxy_url,
                'https': proxy_url
            }
        
        request = requests.post(url, params=params, headers=headers, json=body, proxies=proxies, timeout=(30, 60))
        request.raise_for_status()
        return request.json()
    
    try:
        response_data = await asyncio.to_thread(make_translation_request)
    except requests.exceptions.RequestException as error:
        logger.exception("Translation provider request failed")
        raise HTTPException(
            status_code=502, detail="Translation service unavailable"
        ) from error

    if isinstance(response_data, list) and len(response_data) > 0:
        first_result = response_data[0]
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
        logger.warning(
            "Translation provider returned an unexpected response",
            extra={
                "event": "translator.invalid_response",
                "response_type": type(response_data).__name__,
            },
        )
        raise HTTPException(status_code=400, detail="Translation failed or unexpected response")
