from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infrastructure.integrations.llm import extract_total, normalize_keywords
from infrastructure.integrations.llm.response_parser import _validated_total_response


class FakeUsage:
    def model_dump(self) -> dict[str, int]:
        return {"total_tokens": 3}


class FakeResponse:
    def __init__(self, content: str | None) -> None:
        self.choices = [SimpleNamespace(message=SimpleNamespace(content=content))]
        self.usage = FakeUsage()


class FakeCompletions:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def _client(response: FakeResponse) -> tuple[SimpleNamespace, FakeCompletions]:
    completions = FakeCompletions(response)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)), completions


def _validated(response: FakeResponse):
    return _validated_total_response(
        response,
        logger=logging.getLogger("test.llm"),
        log_message="validation failed",
        log_event="test.validation_failed",
        failure_message="test validation failure",
    )


def test_validated_total_response_handles_null_content() -> None:
    total, usage = _validated(FakeResponse(None))

    assert total.model_dump() == {
        "topics": [],
        "departments": [],
        "keywords": [],
        "overall_sentiment": "neutral",
        "cannot_classified": True,
    }
    assert usage is None


def test_validated_total_response_expands_minimal_unclassified_payload() -> None:
    total, usage = _validated(FakeResponse('{"cannot_classified": true}'))

    assert total.cannot_classified is True
    assert total.topics == []
    assert total.departments == []
    assert total.keywords == []
    assert total.overall_sentiment == "neutral"
    assert usage == {"total_tokens": 3}


def test_validated_total_response_defaults_valid_payload_to_classified() -> None:
    total, usage = _validated(
        FakeResponse(
            '{"topics":[{"text":"Staff","sentiment":"positive"}],'
            '"departments":[{"text":"Sales Ops","sentiment":"positive"}],'
            '"keywords":[{"text":"welcome","sentiment":"positive"}],'
            '"overall_sentiment":"positive"}'
        )
    )

    assert total.cannot_classified is False
    assert total.topics[0].text == "Staff"
    assert usage == {"total_tokens": 3}


@pytest.mark.parametrize(
    "content",
    ["not json", '{"topics": []}'],
    ids=["invalid-json", "invalid-model-data"],
)
def test_validated_total_response_preserves_validation_failure(
    content: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR):
        with pytest.raises(Exception, match="test validation failure"):
            _validated(FakeResponse(content))

    record = caplog.records[-1]
    assert record.message == "validation failed"
    assert record.event == "test.validation_failed"


def test_extract_total_primary_and_retry_preserve_model_settings(monkeypatch) -> None:
    client, completions = _client(FakeResponse('{"cannot_classified": true}'))
    monkeypatch.setattr(extract_total, "get_azure_openai_client", lambda: client)

    primary, _ = extract_total._extract_total_sync("primary comment")
    retry, _ = extract_total._extract_total_retry_sync("retry comment")

    assert primary.cannot_classified is True
    assert retry.cannot_classified is True
    assert [(call["model"], call["temperature"]) for call in completions.calls] == [
        (extract_total.EXTRACT_TOTAL_MODEL, extract_total.EXTRACT_TOTAL_TEMPERATURE),
        (
            extract_total.EXTRACT_TOTAL_RETRY_MODEL,
            extract_total.EXTRACT_TOTAL_RETRY_TEMPERATURE,
        ),
    ]
    assert all(call["response_format"] == {"type": "json_object"} for call in completions.calls)


@pytest.mark.parametrize(
    ("function_name", "expected_message", "expected_event"),
    [
        (
            "_extract_total_sync",
            "Failed to validate classifier response",
            "llm.response_validation_failed",
        ),
        (
            "_extract_total_retry_sync",
            "Failed to validate classifier retry response",
            "llm.retry_response_validation_failed",
        ),
    ],
)
def test_extract_total_preserves_primary_and_retry_validation_errors(
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
    function_name: str,
    expected_message: str,
    expected_event: str,
) -> None:
    client, _ = _client(FakeResponse("not json"))
    monkeypatch.setattr(extract_total, "get_azure_openai_client", lambda: client)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(Exception, match=expected_message):
            getattr(extract_total, function_name)("comment")

    assert caplog.records[-1].event == expected_event


def test_normalize_keywords_preserves_validation_error_and_settings(
    monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    client, completions = _client(FakeResponse("not json"))
    monkeypatch.setattr(normalize_keywords, "get_azure_openai_client", lambda: client)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(Exception, match="Failed to validate keywords response"):
            normalize_keywords._normalize_keywords_sync(
                "comment", {"cannot_classified": True}
            )

    assert len(completions.calls) == 1
    call = completions.calls[0]
    assert call["model"] == normalize_keywords.NORMALIZE_KEYWORDS_MODEL
    assert call["temperature"] == normalize_keywords.NORMALIZE_KEYWORDS_TEMPERATURE
    assert call["response_format"] == {"type": "json_object"}
    assert call["messages"][0]["content"] == normalize_keywords.system_prompt
    assert "comment" in call["messages"][1]["content"]
    assert caplog.records[-1].event == "llm.response_validation_failed"
