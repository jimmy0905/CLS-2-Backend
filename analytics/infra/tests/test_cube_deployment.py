import json
import re
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
SOURCE_COMPOSE = ROOT / "docker-compose.yml"
ANALYTICS_COMPOSE = ROOT / "docker-compose.analytics.yml"
MANIFEST = ROOT / "deploy" / "analytics" / "profiles.json"
GENERATOR = ROOT / "scripts" / "generate_analytics_compose.py"
VALIDATOR = ROOT / "scripts" / "validate_analytics_infra.py"


def _source_profiles() -> list[str]:
    return sorted(
        set(re.findall(r'profiles: \["([a-z0-9_]+)"\]', SOURCE_COMPOSE.read_text()))
    )


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text())


def _compose() -> dict:
    return yaml.safe_load(ANALYTICS_COMPOSE.read_text())


def test_manifest_covers_source_profiles_and_assigns_four_shards_round_robin():
    source_profiles = _source_profiles()
    entries = _manifest()["profiles"]

    assert len(source_profiles) == 61
    assert [entry["name"] for entry in entries] == source_profiles
    assert [entry["cube_store_shard"] for entry in entries] == [
        index % 4 + 1 for index in range(61)
    ]


def test_rollout_manifest_uses_two_canaries_then_waves_of_at_most_ten():
    entries = _manifest()["profiles"]
    waves: dict[int, list[str]] = {}
    for entry in entries:
        waves.setdefault(entry["rollout_wave"], []).append(entry["name"])

    assert set(waves[0]) == {"wtchk_cls", "wtchk_ecls"}
    assert all(len(profiles) <= 10 for wave, profiles in waves.items() if wave > 0)
    assert sorted(profile for profiles in waves.values() for profile in profiles) == _source_profiles()


def test_compose_has_private_api_and_refresh_worker_for_every_profile():
    compose = _compose()
    services = compose["services"]

    for entry in _manifest()["profiles"]:
        profile = entry["name"]
        service_suffix = profile.replace("_", "-")
        api = services[f"cube-api-{service_suffix}"]
        refresh = services[f"cube-refresh-{service_suffix}"]
        backend = services[f"backend-{service_suffix}"]

        assert api["profiles"] == [profile]
        assert refresh["profiles"] == [profile]
        assert "ports" not in api and "ports" not in refresh
        shard_network = f"analytics_store_shard_{entry['cube_store_shard']}"
        assert api["networks"] == ["connex_network", shard_network]
        assert refresh["networks"] == ["connex_network", shard_network]
        assert api["environment"]["CUBEJS_DB_NAME"] == profile
        assert api["environment"]["CUBEJS_APP_ID"] == f"clsense-{profile}"
        assert api["environment"]["CUBEJS_ORCHESTRATOR_ID"] == f"clsense-{profile}"
        assert api["environment"]["CUBEJS_PRE_AGGREGATIONS_SCHEMA"] == (
            f"cube_preagg_{profile}"
        )
        assert api["environment"]["CUBEJS_CUBESTORE_HOST"] == (
            f"cubestore-router-shard-{entry['cube_store_shard']}"
        )
        assert refresh["environment"]["CUBEJS_REFRESH_WORKER"] == "true"
        assert api["environment"]["ANALYTICS_PRE_AGGREGATION_REFRESH_EVERY"] == (
            "${ANALYTICS_PRE_AGGREGATION_REFRESH_EVERY:-15 minute}"
        )
        assert refresh["environment"]["ANALYTICS_PRE_AGGREGATION_REFRESH_EVERY"] == (
            "${ANALYTICS_PRE_AGGREGATION_REFRESH_EVERY:-15 minute}"
        )
        assert "ANALYTICS_SCHEDULED_REFRESH_INTERVAL_SECONDS" not in api["environment"]
        assert refresh["environment"][
            "ANALYTICS_SCHEDULED_REFRESH_INTERVAL_SECONDS"
        ] == "${ANALYTICS_SCHEDULED_REFRESH_INTERVAL_SECONDS:-30}"
        env_prefix = profile.upper()
        assert backend["environment"]["ANALYTICS_ENABLED"] == (
            f"${{{env_prefix}_ANALYTICS_ENABLED:-false}}"
        )
        assert backend["environment"]["ANALYTICS_CUBE_API_URL"] == (
            f"http://cube-api-{service_suffix}:4000"
        )
        assert backend["environment"]["ANALYTICS_EXPORT_DIR"] == (
            "/app/upload_tasks/analytics_exports"
        )
        assert backend["volumes"] == [f"{profile}_upload_tasks:/app/upload_tasks"]


def test_compose_has_four_isolated_cubestore_clusters_with_two_workers_each():
    compose = _compose()
    services = compose["services"]

    for shard in range(1, 5):
        router_name = f"cubestore-router-shard-{shard}"
        worker_names = [
            f"cubestore-worker-{worker}-shard-{shard}" for worker in (1, 2)
        ]
        router = services[router_name]

        assert "ports" not in router
        assert router["networks"] == [f"analytics_store_shard_{shard}"]
        assert router["environment"]["CUBESTORE_REMOTE_DIR"] == (
            f"/cube/data/shard-{shard}"
        )
        assert router["environment"]["CUBESTORE_DATA_DIR"] == "/cube/scratch"
        assert router["environment"]["ANALYTICS_AZURE_BLOB_PREFIX"] == (
            f"${{ANALYTICS_AZURE_BLOB_PREFIX_SHARD_{shard}:-clsense/cubestore/shard-{shard}}}"
        )
        assert "depends_on" not in router

        for worker_name in worker_names:
            worker = services[worker_name]
            assert "ports" not in worker
            assert worker["networks"] == [f"analytics_store_shard_{shard}"]
            assert worker["environment"]["CUBESTORE_META_ADDR"] == (
                f"{router_name}:9999"
            )
            assert worker["depends_on"] == [router_name]


def test_images_require_operator_supplied_tested_digests_and_are_version_pinned():
    compose_text = ANALYTICS_COMPOSE.read_text()
    assert "cubejs/cube:v1.7.26@${CUBE_IMAGE_DIGEST:?" in compose_text
    assert "cubejs/cubestore:v1.7.26@${CUBESTORE_IMAGE_DIGEST:?" in compose_text
    assert 'platform: "${CUBESTORE_PLATFORM:-linux/amd64}"' in compose_text
    assert "sha256:000" not in compose_text
    assert ":latest" not in compose_text


def test_generated_files_are_reproducible():
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_cube_models_keep_assignment_grains_separate_and_use_stable_percentiles():
    model_dir = ROOT / "cube" / "model" / "core"
    model_files = sorted(model_dir.glob("*.yml"))
    models = {path.stem: path.read_text() for path in model_files}

    assert set(models) == {
        "survey_assignments",
        "survey_departments",
        "survey_keywords",
        "survey_responses",
        "survey_topics",
    }
    assert "PERCENTILE_CONT(0.5) WITHIN GROUP" in models["survey_responses"]
    assert "type: number" in models["survey_responses"]
    assert "number_agg" not in "\n".join(models.values())
    response_cube = yaml.safe_load(models["survey_responses"])["cubes"][0]
    response_measures = {
        item["name"]: item for item in response_cube["measures"]
    }
    assert response_measures["responding_store_count"]["sql"] == "store_key"
    assert response_measures["responding_store_count"]["type"] == "count_distinct"
    assert response_measures["responding_store_count"]["meta"] == {
        "query_target": "store",
        "public_aggregation": "count",
        "entity": "store",
    }
    response_dimensions = {
        item["name"]: item for item in response_cube["dimensions"]
    }
    for assignment in ("survey_departments", "survey_keywords", "survey_topics"):
        assert "name: assignment_count" in models[assignment]
        assert "name: survey_count" in models[assignment]
        cube = yaml.safe_load(models[assignment])["cubes"][0]
        dimensions = {item["name"]: item for item in cube["dimensions"]}
        assert dimensions["survey_id"]["type"] == "string"
        assert dimensions["store_name"]["type"] == "string"
        for response_name, response_dimension in response_dimensions.items():
            assignment_name = {
                "id": "response_id",
            }.get(response_name, response_name)
            assert dimensions[assignment_name]["sql"] == response_dimension["sql"]
            assert dimensions[assignment_name]["type"] == response_dimension["type"]
        assert dimensions["sentiment"]["sql"] == "assignment_sentiment"


def test_cube_primary_key_dimensions_are_public():
    model_dir = ROOT / "cube" / "model" / "core"
    expected_primary_keys = {
        "survey_assignments.combination_id",
        "survey_departments.assignment_id",
        "survey_keywords.assignment_id",
        "survey_responses.id",
        "survey_topics.assignment_id",
    }
    public_by_primary_key = {}

    for model_path in sorted(model_dir.glob("*.yml")):
        cube = yaml.safe_load(model_path.read_text())["cubes"][0]
        for dimension in cube["dimensions"]:
            if dimension.get("primary_key") is True:
                member = f"{cube['name']}.{dimension['name']}"
                public_by_primary_key[member] = dimension.get("public")

    assert public_by_primary_key == {
        member: True for member in expected_primary_keys
    }


def test_catalog_contract_is_structured_and_versioned():
    contract = json.loads(
        (ROOT / "cube" / "contracts" / "catalog.schema.json").read_text()
    )
    assert contract["required"] == ["profile", "catalogVersion", "fields", "metrics"]
    assert contract["properties"]["catalogVersion"]["minimum"] == 0
    assert contract["properties"]["fields"]["items"]["additionalProperties"] is False
    assert "rollups" in contract["properties"]


def test_selected_profile_environment_validation_enforces_digest_and_secret_boundaries(
    tmp_path: Path,
):
    digest = "sha256:" + "1" * 64
    good_env = tmp_path / "analytics.env"
    good_env.write_text(
        "\n".join(
            [
                f"CUBE_IMAGE_DIGEST={digest}",
                f"CUBESTORE_IMAGE_DIGEST={digest}",
                "WTCHK_CLS_ANALYTICS_DB_USER=analytics_wtchk_reader",
                "WTCHK_CLS_ANALYTICS_DB_PASSWORD=db-secret",
                f"WTCHK_CLS_CUBE_API_SECRET={'a' * 32}",
                f"WTCHK_CLS_ANALYTICS_METADATA_SECRET={'b' * 32}",
            ]
        )
        + "\n"
    )
    good = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--env-file",
            str(good_env),
            "--profile",
            "wtchk_cls",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert good.returncode == 0, good.stdout + good.stderr

    bad_env = tmp_path / "bad.env"
    bad_env.write_text(
        good_env.read_text()
        .replace(digest, "not-a-digest")
        .replace("analytics_wtchk_reader", "postgres")
        .replace("b" * 32, "a" * 32)
    )
    bad = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--env-file",
            str(bad_env),
            "--profile",
            "wtchk_cls",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert bad.returncode == 1
    assert "tested sha256 digest" in bad.stderr
    assert "dedicated read-only role" in bad.stderr
    assert "signing secrets must be independent" in bad.stderr


def test_profile_validation_rejects_weak_and_cross_profile_reused_signing_secrets(
    tmp_path: Path,
):
    digest = "sha256:" + "2" * 64
    env_file = tmp_path / "analytics.env"
    env_file.write_text(
        "\n".join(
            [
                f"CUBE_IMAGE_DIGEST={digest}",
                f"CUBESTORE_IMAGE_DIGEST={digest}",
                "WTCHK_CLS_ANALYTICS_DB_USER=analytics_wtchk_reader",
                "WTCHK_CLS_ANALYTICS_DB_PASSWORD=db-secret-one",
                "WTCHK_CLS_CUBE_API_SECRET=too-short",
                f"WTCHK_CLS_ANALYTICS_METADATA_SECRET={'m' * 32}",
                "WTCHK_ECLS_ANALYTICS_DB_USER=analytics_wtchk_ecls_reader",
                "WTCHK_ECLS_ANALYTICS_DB_PASSWORD=db-secret-two",
                f"WTCHK_ECLS_CUBE_API_SECRET={'m' * 32}",
                f"WTCHK_ECLS_ANALYTICS_METADATA_SECRET={'n' * 32}",
            ]
        )
        + "\n"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--env-file",
            str(env_file),
            "--profile",
            "wtchk_cls",
            "--profile",
            "wtchk_ecls",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "at least 32 bytes" in result.stderr
    assert "unique across profiles" in result.stderr
