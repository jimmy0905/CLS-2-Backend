#!/usr/bin/env python3
"""Validate generated Cube infrastructure and selected profile credentials."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts" / "generate_analytics_compose.py"
MANIFEST = ROOT / "deploy" / "analytics" / "profiles.json"
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text().splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path}:{line_number}: expected NAME=value")
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip()
    return values


def validate_profile(profile: str, env: dict[str, str], errors: list[str]) -> None:
    prefix = profile.upper()
    required = [
        f"{prefix}_ANALYTICS_DB_USER",
        f"{prefix}_ANALYTICS_DB_PASSWORD",
        f"{prefix}_CUBE_API_SECRET",
        f"{prefix}_ANALYTICS_METADATA_SECRET",
    ]
    for name in required:
        if not env.get(name):
            errors.append(f"{name} is required for active profile {profile}")
    user = env.get(f"{prefix}_ANALYTICS_DB_USER", "")
    if user.lower() in {"postgres", "root", env.get("DATABASE_USER", "").lower()}:
        errors.append(f"{prefix}_ANALYTICS_DB_USER must be a dedicated read-only role")
    api_secret = env.get(f"{prefix}_CUBE_API_SECRET", "")
    metadata_secret = env.get(f"{prefix}_ANALYTICS_METADATA_SECRET", "")
    for name, secret in (
        (f"{prefix}_CUBE_API_SECRET", api_secret),
        (f"{prefix}_ANALYTICS_METADATA_SECRET", metadata_secret),
    ):
        if secret and len(secret.encode("utf-8")) < 32:
            errors.append(f"{name} must contain at least 32 bytes of random data")
    if api_secret and metadata_secret and api_secret == metadata_secret:
        errors.append(f"{profile} API and metadata signing secrets must be independent")


def validate_cross_profile_secrets(
    profiles: list[str], env: dict[str, str], errors: list[str]
) -> None:
    owners: dict[str, str] = {}
    for profile in profiles:
        prefix = profile.upper()
        for suffix in ("CUBE_API_SECRET", "ANALYTICS_METADATA_SECRET"):
            name = f"{prefix}_{suffix}"
            secret = env.get(name, "")
            if not secret:
                continue
            previous = owners.get(secret)
            if previous is not None and previous != name:
                errors.append(
                    f"{name} and {previous} must be unique across profiles and purposes"
                )
            else:
                owners[secret] = name


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--profile", action="append", default=[])
    args = parser.parse_args()

    generated = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"], cwd=ROOT, check=False
    )
    if generated.returncode:
        return generated.returncode

    manifest = json.loads(MANIFEST.read_text())
    known_profiles = {entry["name"] for entry in manifest["profiles"]}
    errors: list[str] = []
    for profile in args.profile:
        if profile not in known_profiles:
            errors.append(f"unknown analytics profile: {profile}")

    if args.profile and args.env_file is None:
        errors.append("--env-file is required when validating an active profile")
    if args.env_file is not None:
        env = read_env(args.env_file)
        for name in ("CUBE_IMAGE_DIGEST", "CUBESTORE_IMAGE_DIGEST"):
            if not DIGEST.fullmatch(env.get(name, "")):
                errors.append(f"{name} must be a tested sha256 digest")
        if env.get("CUBESTORE_PLATFORM", "linux/amd64") != "linux/amd64":
            errors.append("Cube Store v1.7.26 requires CUBESTORE_PLATFORM=linux/amd64")
        prefixes = [
            env.get(
                f"ANALYTICS_AZURE_BLOB_PREFIX_SHARD_{shard}",
                f"clsense/cubestore/shard-{shard}",
            )
            for shard in range(1, 5)
        ]
        if len(set(prefixes)) != 4 or any(not prefix for prefix in prefixes):
            errors.append("the four analytics Azure Blob prefixes must be non-empty and unique")
        for profile in args.profile:
            if profile in known_profiles:
                validate_profile(profile, env, errors)
        validate_cross_profile_secrets(
            [profile for profile in args.profile if profile in known_profiles],
            env,
            errors,
        )

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        f"analytics infrastructure is current: {len(known_profiles)} profiles, "
        "4 Cube Store shards"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
