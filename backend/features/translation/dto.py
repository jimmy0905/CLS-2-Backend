"""Translation endpoint request and response contracts."""

from pydantic import BaseModel


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
