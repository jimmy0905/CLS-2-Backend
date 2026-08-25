import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.analytics_metadata_auth import (
    sign_metadata_request,
    verify_metadata_signature,
)


def test_metadata_signature_is_profile_bound() -> None:
    signature = sign_metadata_request("secret", "wtchk_cls", 1_777_000_000)

    assert verify_metadata_signature(
        "secret", "wtchk_cls", "1777000000", signature, now=1_777_000_120
    )
    assert not verify_metadata_signature(
        "secret", "wtchk_ecls", "1777000000", signature, now=1_777_000_120
    )


def test_metadata_signature_rejects_replay_and_missing_secret() -> None:
    signature = sign_metadata_request("secret", "wtchk_cls", 1_777_000_000)

    assert not verify_metadata_signature(
        "secret", "wtchk_cls", "1777000000", signature, now=1_777_000_301
    )
    assert not verify_metadata_signature(
        "", "wtchk_cls", "1777000000", signature, now=1_777_000_000
    )
