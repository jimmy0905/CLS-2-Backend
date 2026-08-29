from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest


os.environ.setdefault("DATABASE_USER", "test")
os.environ.setdefault("DATABASE_PASSWORD", "test")
os.environ.setdefault("DATABASE_HOST", "localhost")
os.environ.setdefault("DATABASE_PORT", "5432")
os.environ.setdefault("DATABASE_NAME", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.enum.Sentiment import TopicSentiment
from routers import strategy


class FakeQuery:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.order_clause = None
        self.limit_value = None

    def order_by(self, clause):
        self.order_clause = clause
        return self

    def limit(self, value: int):
        self.limit_value = value
        return self

    def all(self) -> list[object]:
        return self.rows


def _assert_query_contract(query: FakeQuery) -> None:
    assert query.limit_value == 30
    assert "length" in str(query.order_clause).lower()
    assert "comment" in str(query.order_clause).lower()
    assert str(query.order_clause).lower().endswith("desc")


def test_positive_strategy_helper_filters_orders_limits_and_dispatches(monkeypatch) -> None:
    rows = [object(), object()]
    query = FakeQuery(rows)
    captured_filters: list[dict] = []
    received_surveys: list[list[object]] = []

    def build_query(db, filters):
        captured_filters.append(filters)
        return query, set(), None

    async def generator(surveys):
        received_surveys.append(surveys)
        return "generated strategy", {}

    monkeypatch.setattr(strategy, "build_optimized_query", build_query)

    result = asyncio.run(
        strategy._generate_positive_strategy(
            object(),
            filter_key="store_keys",
            filter_values=["store-1"],
            generator=generator,
        )
    )

    assert result == "generated strategy"
    assert captured_filters == [
        {"store_keys": ["store-1"], "topic_sentiments": [TopicSentiment.POSITIVE]}
    ]
    assert received_surveys == [rows]
    _assert_query_contract(query)


@pytest.mark.parametrize(
    ("endpoint", "endpoint_request", "filter_key", "values", "generator_name"),
    [
        (
            strategy.get_strategy_for_store_by_ids,
            strategy.StrategyByStoreIdsRequest(store_keys=["store-1"]),
            "store_keys",
            ["store-1"],
            "generate_store_strategy",
        ),
        (
            strategy.get_top_k_performance_channels_by_ids,
            strategy.TopKPerformanceByChannelIdsRequest(channel_ids=[11]),
            "channel_ids",
            [11],
            "generate_channel_strategy",
        ),
        (
            strategy.get_top_k_performance_delivery_services_by_ids,
            strategy.TopKPerformanceByDeliveryServiceIdsRequest(
                delivery_service_ids=[7]
            ),
            "delivery_service_ids",
            [7],
            "generate_delivery_service_strategy",
        ),
    ],
)
def test_id_strategy_endpoints_preserve_filter_and_generator(
    monkeypatch, endpoint, endpoint_request, filter_key, values, generator_name
) -> None:
    rows = [object()]
    query = FakeQuery(rows)
    captured_filters: list[dict] = []
    generator_calls: list[list[object]] = []

    def build_query(db, filters):
        captured_filters.append(filters)
        return query, set(), None

    async def generator(surveys):
        generator_calls.append(surveys)
        return f"{filter_key} strategy", {}

    monkeypatch.setattr(strategy, "build_optimized_query", build_query)
    monkeypatch.setattr(strategy, generator_name, generator)

    result = asyncio.run(endpoint(endpoint_request, db=object()))

    assert result == f"{filter_key} strategy"
    assert captured_filters == [
        {filter_key: values, "topic_sentiments": [TopicSentiment.POSITIVE]}
    ]
    assert generator_calls == [rows]
    _assert_query_contract(query)
