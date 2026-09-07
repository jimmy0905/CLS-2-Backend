from datetime import UTC, datetime

from features.analytics.prewarm import RollupSpec, _catalog_rollups, warmup_batches


def test_catalog_rollups_preserve_partition_granularity() -> None:
    snapshot = {
        "cubeCatalog": {
            "rollups": [
                {
                    "semanticView": "catalog_3_feedback",
                    "name": "chart_3_feedback",
                    "partitionGranularity": "month",
                },
                {
                    "semanticView": "catalog_3_summary",
                    "name": "chart_3_summary",
                },
            ]
        }
    }

    assert _catalog_rollups(snapshot) == [
        RollupSpec(
            name="catalog_3_feedback.chart_3_feedback",
            partition_granularity="month",
        ),
        RollupSpec(
            name="catalog_3_summary.chart_3_summary",
            partition_granularity=None,
        ),
    ]


def test_warmup_batches_cover_historical_partitions_and_remain_queue_safe() -> None:
    rollups = (
        *(
            RollupSpec(
                name=f"survey_responses.month_{index}",
                partition_granularity="month",
            )
            for index in range(9)
        ),
        RollupSpec(name="survey_responses.yearly", partition_granularity="year"),
        RollupSpec(name="survey_responses.unpartitioned", partition_granularity=None),
    )

    batches = warmup_batches(
        rollups,
        minimum=datetime(2025, 12, 31, 20, tzinfo=UTC),
        maximum=datetime(2026, 2, 1, 2, tzinfo=UTC),
        timezone_names=("UTC", "Asia/Hong_Kong"),
    )

    assert batches
    assert all(len(batch.pre_aggregations) <= 8 for batch in batches)
    assert {
        batch.date_range
        for batch in batches
        if batch.timezone_name == "UTC"
        and batch.date_range is not None
        and any("month_" in name for name in batch.pre_aggregations)
    } == {
        ("2025-12-01", "2025-12-31"),
        ("2026-01-01", "2026-01-31"),
        ("2026-02-01", "2026-02-28"),
    }
    assert {
        batch.date_range
        for batch in batches
        if batch.timezone_name == "Asia/Hong_Kong"
        and "survey_responses.yearly" in batch.pre_aggregations
    } == {("2026-01-01", "2026-12-31")}
    assert any(batch.date_range is None for batch in batches)
