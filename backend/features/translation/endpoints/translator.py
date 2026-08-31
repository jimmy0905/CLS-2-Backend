from fastapi import APIRouter, Depends

from core.security import ActorContext
from features.identity.service.security import get_current_actor
from features.translation.dto import (
    DetectedLanguage,
    Translation,
    TranslationRequest,
    TranslationResponse,
)
from features.translation.service import translation_service
from infrastructure.database.session import get_db

router = APIRouter(
    prefix="/translator",
    tags=["translator"],
    dependencies=[Depends(get_db), Depends(get_current_actor)],
)


@router.post("/translate")
async def translate(
    translation_request: TranslationRequest,
    current_user: ActorContext = Depends(get_current_actor),
) -> TranslationResponse:
    first_result = await translation_service.translate(
        translation_request.text, translation_request.target_language
    )
    return TranslationResponse(
        detected_language=DetectedLanguage(
            language=first_result["detectedLanguage"]["language"],
            score=first_result["detectedLanguage"]["score"],
        ),
        translations=[
            Translation(text=translation["text"], to=translation["to"])
            for translation in first_result["translations"]
        ],
    )
