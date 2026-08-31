from pathlib import Path
import sys
import unittest

from sqlalchemy import UniqueConstraint


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class AnalyticsCatalogModelTests(unittest.TestCase):
    def test_catalog_models_are_registered_with_governance_columns(self) -> None:
        from infrastructure.database.registry import (
            AnalyticsChart,
            AnalyticsExportJob,
            AnalyticsField,
            AnalyticsFieldValue,
            AnalyticsMetric,
            AnalyticsModelVersion,
            AnalyticsQueryLog,
            Base,
            UploadTask,
        )

        expected_tables = {
            "analytics_fields",
            "analytics_metrics",
            "analytics_charts",
            "analytics_model_versions",
            "analytics_query_logs",
            "analytics_export_jobs",
            "analytics_field_values",
        }
        self.assertTrue(expected_tables.issubset(Base.metadata.tables))

        self.assertTrue(
            {
                "inferred_data_type",
                "type_conflicts",
                "sample_values",
                "semantic_view",
                "visibility",
                "published_at",
                "archived_at",
                "last_seen_at",
            }.issubset(AnalyticsField.__table__.columns.keys())
        )
        self.assertTrue(
            {
                "slug",
                "semantic_view",
                "field_id",
                "source_member",
                "operation",
                "weight_field_id",
                "weight_member",
                "definition",
                "visibility",
                "status",
                "published_model_version_id",
            }.issubset(AnalyticsMetric.__table__.columns.keys())
        )
        self.assertTrue(
            {
                "slug",
                "semantic_view",
                "visibility",
                "validated_at",
                "validation_errors",
                "published_model_version_id",
                "archived_at",
            }.issubset(AnalyticsChart.__table__.columns.keys())
        )
        self.assertTrue(
            {"catalog_version", "definition_hash", "catalog_snapshot", "is_active"}.issubset(
                AnalyticsModelVersion.__table__.columns.keys()
            )
        )
        self.assertIn("request", AnalyticsQueryLog.__table__.columns)
        self.assertIn("expires_at", AnalyticsExportJob.__table__.columns)
        self.assertTrue(AnalyticsFieldValue.__deprecated__)
        self.assertTrue(AnalyticsField.created_by_subject.nullable)
        self.assertTrue(
            {"analytics_affected_months", "analytics_refresh_status"}.issubset(
                UploadTask.__table__.columns.keys()
            )
        )

    def test_metric_and_catalog_version_identity_is_unique(self) -> None:
        from infrastructure.database.registry import AnalyticsMetric, AnalyticsModelVersion

        metric_constraints = {
            constraint.name
            for constraint in AnalyticsMetric.__table__.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        version_constraints = {
            constraint.name
            for constraint in AnalyticsModelVersion.__table__.constraints
            if isinstance(constraint, UniqueConstraint)
        }

        self.assertIn("uq_analytics_metrics_slug", metric_constraints)
        self.assertIn("uq_analytics_model_versions_catalog_version", version_constraints)

    def test_foreign_keys_preserve_published_definition_dependencies(self) -> None:
        from infrastructure.database.registry import AnalyticsChart, AnalyticsMetric

        metric_foreign_keys = {
            (foreign_key.parent.name, foreign_key.target_fullname)
            for foreign_key in AnalyticsMetric.__table__.foreign_keys
        }
        chart_foreign_keys = {
            (foreign_key.parent.name, foreign_key.target_fullname)
            for foreign_key in AnalyticsChart.__table__.foreign_keys
        }

        self.assertIn(("field_id", "analytics_fields.id"), metric_foreign_keys)
        self.assertIn(("weight_field_id", "analytics_fields.id"), metric_foreign_keys)
        self.assertIn(
            ("published_model_version_id", "analytics_model_versions.id"),
            metric_foreign_keys,
        )
        self.assertIn(
            ("published_model_version_id", "analytics_model_versions.id"),
            chart_foreign_keys,
        )


class AnalyticsCatalogMigrationTests(unittest.TestCase):
    def test_follow_up_migration_adds_json_helpers_and_separate_grain_views(self) -> None:
        migration_path = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "versions"
            / "2026_08_25_0008_0009_add_cube_semantic_catalog.py"
        )
        migration = migration_path.read_text()

        self.assertIn('down_revision: Union[str, Sequence[str], None] = "0008_log_retention_indexes"', migration)
        self.assertIn("analytics_normalize_raw_row", migration)
        self.assertIn("analytics_raw_value", migration)
        self.assertIn("analytics_raw_number", migration)
        self.assertIn("analytics_raw_number_invalid", migration)
        self.assertIn("analytics_raw_boolean", migration)
        self.assertIn("analytics_raw_date", migration)
        self.assertIn("analytics_raw_time", migration)
        self.assertIn("analytics_raw_timestamp", migration)
        self.assertIn("bare NaN/Infinity", migration)
        self.assertIn('"semantic_view"', migration)
        self.assertIn('"analytics_affected_months"', migration)
        self.assertIn('"analytics_refresh_status"', migration)
        self.assertIn("CREATE VIEW analytics_survey_topics", migration)
        self.assertIn("CREATE VIEW analytics_survey_departments", migration)
        self.assertIn("CREATE VIEW analytics_survey_keywords", migration)
        self.assertIn("assignment_count", migration)
        self.assertEqual(migration.count("            st.sic,"), 1)
        self.assertNotIn("DROP TABLE analytics_field_values", migration)
        self.assertIn("UPDATE analytics_fields", migration)


if __name__ == "__main__":
    unittest.main()
