import csv
import sys
from pathlib import Path

import pytest
from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.analytics_exports import (
    authorize_export_role,
    build_export_path,
    cube_response_rows,
    ensure_export_model_version,
    remove_export_file,
    write_export,
)
from types import SimpleNamespace


def test_export_path_is_confined_to_the_export_root(tmp_path: Path) -> None:
    path = build_export_path(
        tmp_path, "65f5af41-2d68-4dd8-b414-c7953721924d", "csv"
    )

    assert path.parent == tmp_path.resolve()
    assert path.name == "65f5af41-2d68-4dd8-b414-c7953721924d.csv"
    with pytest.raises(ValueError):
        build_export_path(tmp_path, "../../escape", "csv")
    with pytest.raises(ValueError):
        build_export_path(tmp_path, "65f5af41-2d68-4dd8-b414-c7953721924d", "html")


def test_csv_export_escapes_spreadsheet_formulas(tmp_path: Path) -> None:
    path = tmp_path / "result.csv"

    count = write_export(
        [{"store": "A", "comment": "=HYPERLINK('bad')", "score": 4}],
        "csv",
        path,
        max_rows=10,
    )

    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert count == 1
    assert rows[0]["comment"] == "'=HYPERLINK('bad')"


def test_xlsx_export_escapes_formulas_and_enforces_cap(tmp_path: Path) -> None:
    path = tmp_path / "result.xlsx"

    write_export([{"value": "+1+1"}], "xlsx", path, max_rows=1)

    workbook = load_workbook(path, read_only=True, data_only=False)
    assert workbook.active["A2"].value == "'+1+1"
    with pytest.raises(ValueError, match="row limit"):
        write_export([{"value": 1}, {"value": 2}], "xlsx", path, max_rows=1)


def test_expiry_removes_only_files_inside_export_root(tmp_path: Path) -> None:
    root = tmp_path / "exports"
    root.mkdir()
    inside = root / "result.csv"
    outside = tmp_path / "keep.csv"
    inside.touch()
    outside.touch()

    assert remove_export_file(root, str(inside))
    assert not inside.exists()
    assert not remove_export_file(root, str(outside))
    assert outside.exists()


def test_cube_export_rows_require_a_list_of_objects() -> None:
    assert cube_response_rows({"data": [{"count": "2"}]}) == [{"count": "2"}]
    with pytest.raises(ValueError, match="invalid data"):
        cube_response_rows({"data": "bad"})
    with pytest.raises(ValueError, match="invalid row"):
        cube_response_rows({"data": ["bad"]})


def test_queued_admin_export_rechecks_role_before_execution() -> None:
    assert authorize_export_role(
        "viewer", SimpleNamespace(role="admin", is_deleted=False)
    ) == "viewer"
    assert authorize_export_role(
        "admin", SimpleNamespace(role="admin", is_deleted=False)
    ) == "admin"
    with pytest.raises(PermissionError, match="revoked"):
        authorize_export_role(
            "admin", SimpleNamespace(role="user", is_deleted=False)
        )
    with pytest.raises(PermissionError, match="no longer active"):
        authorize_export_role(
            "viewer", SimpleNamespace(role="user", is_deleted=True)
        )


def test_queued_export_rejects_catalog_version_drift() -> None:
    ensure_export_model_version(4, 4)
    ensure_export_model_version(None, None)
    with pytest.raises(ValueError, match="catalog changed"):
        ensure_export_model_version(4, 5)
