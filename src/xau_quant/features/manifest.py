"""Feature dataset manifest creation and cryptographic provenance management."""

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import duckdb

from xau_quant.common.paths import project_paths
from xau_quant.features.models import FeatureDatasetManifest
from xau_quant.features.registry import FeatureRegistry


def build_feature_dataset_manifest(
    dataset_id: str,
    partitions: List[Dict[str, Any]],
    total_rows: int,
    valid_rows: int,
    warmup_rows: int,
    gap_rows: int,
    domain_nan_rows: int,
    registry: Optional[FeatureRegistry] = None,
    input_manifest_path: Optional[Path] = None,
    venue: str = "binance",
    instrument: str = "BTCUSDT",
    primary_timeframe: str = "5m",
    feature_set_version: str = "v2.0.0",
    session_definition_version: str = "1.0.0",
) -> Tuple[FeatureDatasetManifest, Path, str]:
    """Build and persist authoritative feature dataset manifest with cryptographic lineage.

    Returns:
        Tuple of (manifest_model, saved_path, manifest_sha256).
    """
    reg = registry or FeatureRegistry()

    # Load and hash the Phase 1C canonical root manifest
    in_manifest_path = (
        input_manifest_path
        or project_paths.data_metadata
        / "manifests"
        / "binance_spot_btcusdt_canonical_v1.1.0_manifest.json"
    )
    if in_manifest_path.exists():
        in_bytes = in_manifest_path.read_bytes()
        in_manifest_sha256 = hashlib.sha256(in_bytes).hexdigest()
        in_manifest_data = json.loads(in_bytes.decode("utf-8"))
    else:
        in_manifest_sha256 = "UNKNOWN"
        in_manifest_data = {}

    first_ts = partitions[0]["first_timestamp_utc"] if partitions else None
    last_ts = partitions[-1]["last_timestamp_utc"] if partitions else None

    # Calculate overall dataset SHA-256 (hash of all partition hashes in deterministic order)
    combined_partition_hashes = "".join(p["sha256"] for p in partitions)
    dataset_sha256 = hashlib.sha256(combined_partition_hashes.encode("utf-8")).hexdigest()

    # Build catalog summary
    feature_catalog = {
        "total_features": reg.total_feature_count(),
        "total_columns": reg.total_column_count(),
        "max_required_history_bars": reg.max_required_history_bars(),
        "counts_by_family": reg.counts_by_family(),
        "features": [
            {
                "name": f.name,
                "family": f.family,
                "required_history_bars": f.required_history_bars,
                "estimator_type": f.estimator_type,
                "temporal_semantics": f.temporal_semantics,
                "columns": [
                    {"name": c.name, "type": c.duckdb_type, "nullable": c.nullable}
                    for c in f.columns
                ],
            }
            for f in reg.get_ordered_features()
        ],
    }

    manifest_dict: Dict[str, Any] = {
        "schema_version": "2.0.0",
        "feature_set_version": feature_set_version,
        "dataset_id": dataset_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_dataset": {
            "dataset_version": in_manifest_data.get("dataset_version", "v1.1.0"),
            "dataset_id": in_manifest_data.get(
                "dataset_id", "binance_spot_btcusdt_canonical_v1.1.0"
            ),
            "manifest_path": in_manifest_path.as_posix(),
            "manifest_sha256": in_manifest_sha256,
            "venue": venue,
            "instrument": instrument,
            "timeframe": primary_timeframe,
            "total_canonical_rows": total_rows,
        },
        "engine": {
            "name": "xau_quant.features",
            "version": "2.0.0",
            "duckdb_version": duckdb.__version__,
            "python_version": sys.version.split()[0],
            "platform": sys.platform,
        },
        "session_definition_version": session_definition_version,
        "feature_clock": {
            "primary_timeframe": primary_timeframe,
            "context_timeframes": ["1m", "15m", "1h"],
            "alignment_rule": "latest_completed_htf_candle_at_close",
        },
        "coverage": {
            "first_timestamp_utc": first_ts,
            "last_timestamp_utc": last_ts,
            "total_rows": total_rows,
            "valid_rows": valid_rows,
            "warmup_rows": warmup_rows,
            "gap_rows": gap_rows,
            "domain_nan_rows": domain_nan_rows,
            "warmup_threshold_bars": 311,
        },
        "feature_catalog": feature_catalog,
        "determinism": {
            "dataset_sha256": dataset_sha256,
            "partitions_count": len(partitions),
            "determinism_target_same_runtime": "byte_identical_parquet",
            "determinism_target_cross_runtime": "identical_schema_ordering_and_float_tolerance",
        },
        "storage": {
            "format": "parquet",
            "compression": "zstd",
            "partitioning": ["year", "month"],
            "partitions": partitions,
        },
    }

    manifest = FeatureDatasetManifest(**manifest_dict)

    # Save manifest
    manifest_dir = project_paths.data_metadata / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{dataset_id}_manifest.json"

    content_bytes = json.dumps(manifest_dict, indent=2).encode("utf-8")
    manifest_path.write_bytes(content_bytes)
    manifest_hash = hashlib.sha256(content_bytes).hexdigest()

    return manifest, manifest_path, manifest_hash
