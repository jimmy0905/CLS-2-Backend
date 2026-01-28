from fastapi import APIRouter, Depends, HTTPException
from utils.database import get_db
from utils.security import get_current_user
from pydantic import BaseModel
from azure.ai.translation.text.models import InputTextItem
from models.User import User
import os
from azure.ai.translation.text import TextTranslationClient, TranslatorCredential
import uuid
import requests

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
    url = f"{endpoint}/translate"
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

    request = requests.post(url, params=params, headers=headers, json=body, proxies={
        'http': os.getenv("ASW_PROXY_URL"),
        'https': os.getenv("ASW_PROXY_URL"),
    })
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