"""Integration tests for the complete Phase 2 Feature Pipeline and dataset artifacts."""

import json

import duckdb
import pytest

from xau_quant.common.paths import project_paths
from xau_quant.features.registry import FeatureRegistry
from xau_quant.features.storage import FeatureParquetStorage


@pytest.fixture(scope="module")
def feature_dataset_info():
    """Discover feature dataset partitions and manifest."""
    registry = FeatureRegistry()
    storage = FeatureParquetStorage(registry=registry)
    partitions = storage.discover_partitions(
        venue="binance",
        market_type="spot",
        instrument="BTCUSDT",
        timeframe="5m",
        feature_set_version="v2.0.0",
    )
    manifest_path = (
        project_paths.data_metadata / "manifests" / "btcusdt_5m_features_v2.0.0_manifest.json"
    )

    assert len(partitions) == 37, f"Expected 37 monthly partitions, found {len(partitions)}"
    assert manifest_path.exists(), f"Feature dataset manifest not found at {manifest_path}"

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)

    return {
        "partitions": [p.as_posix() for p in partitions],
        "manifest_path": manifest_path,
        "manifest": manifest_data,
        "registry": registry,
    }


def test_ac3_row_count_matches_canonical_5m(feature_dataset_info):
    """AC-3: Total row count matches 5m canonical candles exactly (315,648)."""
    con = duckdb.connect(":memory:")
    try:
        count = con.execute(
            "SELECT COUNT(*) FROM read_parquet(?)",
            [feature_dataset_info["partitions"]],
        ).fetchone()[0]
        assert count == 315648
        assert feature_dataset_info["manifest"]["coverage"]["total_rows"] == 315648
    finally:
        con.close()


def test_ac4_zero_infinities(feature_dataset_info):
    """AC-4: Zero inf or -inf across all feature columns."""
    reg = feature_dataset_info["registry"]
    double_cols = [c.name for c in reg.get_all_column_specs() if c.duckdb_type == "DOUBLE"]

    con = duckdb.connect(":memory:")
    try:
        inf_checks = " + ".join(
            [f"COUNT(CASE WHEN isinf(\"{c}\") THEN 1 END)" for c in double_cols]
        )
        total_infs = con.execute(
            f"SELECT {inf_checks} FROM read_parquet(?)",
            [feature_dataset_info["partitions"]],
        ).fetchone()[0]
        assert total_infs == 0, f"Found {total_infs} infinite values!"
    finally:
        con.close()


def test_ac5_ac6_warmup_and_validity(feature_dataset_info):
    """AC-5 & AC-6: Warmup rows=311, valid=315,337, zero unexplained invalid post-warmup rows."""
    con = duckdb.connect(":memory:")
    try:
        parts = feature_dataset_info["partitions"]
        warmup_count = con.execute(
            "SELECT COUNT(*) FROM read_parquet(?) WHERE is_warmup = TRUE",
            [parts],
        ).fetchone()[0]
        assert warmup_count == 311

        valid_count = con.execute(
            "SELECT COUNT(*) FROM read_parquet(?) WHERE is_valid = TRUE",
            [parts],
        ).fetchone()[0]
        assert valid_count == 315648 - 311

        # Zero invalid post-warmup rows in this continuous dataset
        invalid_post_warmup = con.execute(
            "SELECT COUNT(*) FROM read_parquet(?) WHERE is_warmup = FALSE AND is_valid = FALSE",
            [parts],
        ).fetchone()[0]
        assert invalid_post_warmup == 0
    finally:
        con.close()


def test_ac16_provenance_link_to_phase_1c_root(feature_dataset_info):
    """AC-16: Provenance hash linked to Phase 1C root manifest."""
    manifest = feature_dataset_info["manifest"]
    input_ds = manifest["input_dataset"]
    assert input_ds["dataset_version"] == "v1.1.0"
    assert input_ds["dataset_id"] == "binance_spot_btcusdt_canonical_v1.1.0"
    assert len(input_ds["manifest_sha256"]) == 64
    assert input_ds["manifest_sha256"] != "UNKNOWN"
