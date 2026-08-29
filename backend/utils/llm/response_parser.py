import json
from logging import Logger
from typing import Any

from utils.llm.models import TotalResponse
from utils.llm.text_cleaning_helper import _clean_response_content


def _validated_total_response(
    response: Any,
    *,
    logger: Logger,
    log_message: str,
    log_event: str,
    failure_message: str,
) -> tuple[TotalResponse, dict | None]:
    """Validate a classifier response while preserving caller-specific failures."""
    response_content = response.choices[0].message.content
    if response_content is None:
        return (
            TotalResponse(
                topics=[],
                departments=[],
                keywords=[],
                overall_sentiment="neutral",
                cannot_classified=True,
            ),
            None,
        )

    try:
        response_json = json.loads(_clean_response_content(response_content))
        if response_json.get("cannot_classified") is True:
            response_json = {
                "topics": [],
                "departments": [],
                "keywords": [],
                "overall_sentiment": "neutral",
                "cannot_classified": True,
            }
        else:
            response_json.setdefault("cannot_classified", False)

        return TotalResponse.model_validate(response_json), response.usage.model_dump()
    except Exception as error:
        logger.error(
            log_message,
            extra={
                "event": log_event,
                "response_length": len(response_content),
                "error_type": type(error).__name__,
            },
        )
        raise Exception(failure_message) from error
