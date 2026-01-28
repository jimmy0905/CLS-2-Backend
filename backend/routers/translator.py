from fastapi import APIRouter, Depends, HTTPException
from utils.database import get_db
from utils.security import get_current_user
from pydantic import BaseModel
from sqlalchemy.orm import Session
from azure.ai.translation.text import TextTranslationClient, TranslatorCredential
from azure.ai.translation.text.models import InputTextItem
from azure.core.exceptions import HttpResponseError
import os
import requests
from azure.core.pipeline.transport import RequestsTransport
from models.User import User

router = APIRouter(
    prefix="/translator",
    tags=["translator"],
    dependencies=[Depends(get_db), Depends(get_current_user)],
)

key = os.getenv("AZURE_TRANSLATOR_KEY")
endpoint = os.getenv("AZURE_TRANSLATOR_ENDPOINT")
region = os.getenv("AZURE_TRANSLATOR_REGION")
credential = TranslatorCredential(key, region)

# Configure proxy
proxy_url = os.getenv("ASW_PROXY_URL")
if proxy_url:
    # Remove trailing slash if present
    if proxy_url.endswith("/"):
        proxy_url = proxy_url[:-1]
    
    # Create a custom session with proxy settings
    session = requests.Session()
    session.proxies = {"http": proxy_url, "https": proxy_url}
    session.verify = False  # Disable SSL verification for proxy
    
    # Use RequestsTransport with the custom session
    transport = RequestsTransport(session=session)
    
    text_translator = TextTranslationClient(
        endpoint=endpoint,
        credential=credential,
        transport=transport
    )
else:
    text_translator = TextTranslationClient(
        endpoint=endpoint,
        credential=credential,
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
    response = text_translator.translate(
        [InputTextItem(text=translation_request.text)],
        to=[translation_request.target_language],
    )
    translation = response[0] if response else None
    if translation:
        return TranslationResponse(
            detected_language=DetectedLanguage(
                language=translation.detected_language.language,
                score=translation.detected_language.score,
            ),
            translations=[
                Translation(
                    text=translated_text.text,
                    to=translated_text.to,
                )
                for translated_text in translation.translations
            ],
        )
    else:
        raise HTTPException(status_code=400, detail="No translation found")


@router.get("/get-available-languages")
async def get_available_languages():
    return text_translator.get_languages()
