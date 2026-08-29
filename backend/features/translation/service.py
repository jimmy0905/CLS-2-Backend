"""Translation use cases and provider-error classification."""

import asyncio
from typing import Any, cast

import requests

from core.errors import IntegrationError, ValidationError
from core.logging import logger
from infrastructure.integrations.translation import translate


class TranslationService:
    async def translate(self, text: str, target_language: str) -> dict[str, Any]:
        try:
            response = await asyncio.to_thread(translate, text, target_language)
        except requests.exceptions.RequestException as error:
            logger.exception("Translation provider request failed")
            raise IntegrationError("Translation service unavailable") from error
        if not isinstance(response, list) or not response:
            logger.warning(
                "Translation provider returned an unexpected response",
                extra={
                    "event": "translator.invalid_response",
                    "response_type": type(response).__name__,
                },
            )
            raise ValidationError("Translation failed or unexpected response")
        return cast(dict[str, Any], response[0])


translation_service = TranslationService()
