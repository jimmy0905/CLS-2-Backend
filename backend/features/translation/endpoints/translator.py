from fastapi import APIRouter, Depends
from infrastructure.database.session import get_db
from features.identity.service.security import get_current_user
from infrastructure.database.dbo.User import User
from features.translation.dto import (
    DetectedLanguage,
    Translation,
    TranslationRequest,
    TranslationResponse,
)
from features.translation.service import translation_service

router = APIRouter(
    prefix="/translator",
    tags=["translator"],
    dependencies=[Depends(get_db), Depends(get_current_user)],
)


@router.post("/translate")
async def translate(
    translation_request: TranslationRequest,
    current_user: User = Depends(get_current_user),
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
