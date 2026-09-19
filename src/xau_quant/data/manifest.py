"""Dataset provenance manifest generator establishing cryptographic lineage."""

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from xau_quant.common.paths import project_paths
from xau_quant.data.validator import ValidationReport


@dataclass
class ProvenanceManifest:
    """Authoritative metadata manifest capturing lineage and cryptographic hashes."""

    dataset_id: str
    venue: str
    instrument: str
    market_type: str
    timeframe: str
    source_endpoint: str
    requested_start: Optional[str]
    requested_end: Optional[str]
    actual_start: Optional[str]
    actual_end: Optional[str]
    acquisition_timestamp_utc: str
    schema_version: str
    raw_file_path: str
    raw_file_hash_sha256: str
    normalized_file_path: str
    normalized_file_hash_sha256: str
    raw_row_count: int
    normalized_row_count: int
    validation_status: str  # "PASS" or "FAIL"
    validation_summary: Dict[str, Any]
    parent_manifest_id: Optional[str] = None
    constituent_timeframe: Optional[str] = None
    raw_chunks_count: Optional[int] = None
    raw_files_hashes: Optional[List[Dict[str, str]]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert manifest to JSON-serializable dictionary."""
        return asdict(self)

    def save_authoritative(self, output_dir: Optional[Path] = None) -> Tuple[Path, str]:
        """Save the single authoritative manifest under data/metadata/manifests/."""
        if output_dir is None:
            output_dir = project_paths.data_metadata / "manifests"
        output_dir.mkdir(parents=True, exist_ok=True)

        target_path = output_dir / f"{self.dataset_id}_manifest.json"
        content_bytes = json.dumps(self.to_dict(), indent=2).encode("utf-8")
        target_path.write_bytes(content_bytes)

        manifest_hash = hashlib.sha256(content_bytes).hexdigest()
        return target_path, manifest_hash

    @staticmethod
    def create_artifact_copy(
        authoritative_path: Path, artifact_dir: Optional[Path] = None
    ) -> Tuple[Path, str]:
        """Create a research artifact copy under artifacts/datasets/ with identical hash."""
        if not authoritative_path.exists():
            raise FileNotFoundError(f"Authoritative manifest not found: {authoritative_path}")

        if artifact_dir is None:
            artifact_dir = project_paths.artifacts_datasets
        artifact_dir.mkdir(parents=True, exist_ok=True)

        dest_path = artifact_dir / authoritative_path.name
        shutil.copy2(authoritative_path, dest_path)

        auth_hash = hashlib.sha256(authoritative_path.read_bytes()).hexdigest()
        dest_hash = hashlib.sha256(dest_path.read_bytes()).hexdigest()
        if auth_hash != dest_hash:
            raise RuntimeError(
                f"Manifest copy hash mismatch! Auth: {auth_hash} != Copy: {dest_hash}"
            )

        return dest_path, dest_hash

    @classmethod
    def build(
        cls,
        dataset_id: str,
        venue: str,
        instrument: str,
        market_type: str,
        timeframe: str,
        source_endpoint: str,
        raw_file_path: Path,
        normalized_file_path: Path,
        raw_row_count: int,
        normalized_row_count: int,
        validation_report: ValidationReport,
        requested_start: Optional[str] = None,
        requested_end: Optional[str] = None,
        actual_start: Optional[str] = None,
        actual_end: Optional[str] = None,
        schema_version: str = "1.0.0",
        parent_manifest_id: Optional[str] = None,
        constituent_timeframe: Optional[str] = None,
        raw_chunks_count: Optional[int] = None,
        raw_files_hashes: Optional[List[Dict[str, str]]] = None,
    ) -> "ProvenanceManifest":
        """Build ProvenanceManifest from actual file paths and validation findings."""
        raw_sha256 = ""
        if raw_file_path.exists():
            raw_bytes = raw_file_path.read_bytes()
            raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()

        norm_bytes = normalized_file_path.read_bytes()
        norm_sha256 = hashlib.sha256(norm_bytes).hexdigest()

        acq_time_utc = datetime.now(timezone.utc).isoformat()
        val_status = "PASS" if validation_report.is_valid else "FAIL"

        return cls(
            dataset_id=dataset_id,
            venue=venue,
            instrument=instrument,
            market_type=market_type,
            timeframe=timeframe,
            source_endpoint=source_endpoint,
            requested_start=requested_start,
            requested_end=requested_end,
            actual_start=actual_start,
            actual_end=actual_end,
            acquisition_timestamp_utc=acq_time_utc,
            schema_version=schema_version,
            raw_file_path=str(raw_file_path),
            raw_file_hash_sha256=raw_sha256,
            normalized_file_path=str(normalized_file_path),
            normalized_file_hash_sha256=norm_sha256,
            raw_row_count=raw_row_count,
            normalized_row_count=normalized_row_count,
            validation_status=val_status,
            validation_summary=validation_report.summary_dict(),
            parent_manifest_id=parent_manifest_id,
            constituent_timeframe=constituent_timeframe,
            raw_chunks_count=raw_chunks_count,
            raw_files_hashes=raw_files_hashes,
        )


@dataclass
class PartitionManifest:
    """Lineage manifest for a single monthly partition."""

    partition_id: str
    year: int
    month: int
    instrument: str
    venue: str
    market_type: str
    timeframe: str
    start_utc: str
    end_utc: str
    row_count: int
    parquet_path: str
    parquet_sha256: str
    raw_source_files: List[Dict[str, Any]]
    validation_status: str
    created_at_utc: str
    schema_version: str = "1.1.0"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def save(self, output_dir: Optional[Path] = None) -> Tuple[Path, str]:
        if output_dir is None:
            output_dir = project_paths.data_metadata / "manifests" / "partitions"
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / f"{self.partition_id}_manifest.json"
        content_bytes = json.dumps(self.to_dict(), indent=2).encode("utf-8")
        target.write_bytes(content_bytes)
        file_hash = hashlib.sha256(content_bytes).hexdigest()
        return target, file_hash


@dataclass
class RootDatasetManifest:
    """Root multi-year dataset manifest capturing overall lineage and partition catalog."""

    dataset_version: str
    dataset_id: str
    venue: str
    instrument: str
    market_type: str
    base_timeframe: str
    derived_timeframes: List[str]
    start_utc: str
    end_utc: str
    total_calendar_days: int
    total_1m_rows: int
    total_partitions: int
    partition_manifest_paths: List[str]
    validation_status: str
    validation_summary: Dict[str, Any]
    storage_summary: Dict[str, Any]
    created_at_utc: str
    schema_version: str = "1.1.0"
    parent_dataset_version: Optional[str] = "v1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def save(self, output_dir: Optional[Path] = None) -> Tuple[Path, str]:
        if output_dir is None:
            output_dir = project_paths.data_metadata / "manifests"
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / f"{self.dataset_id}_manifest.json"
        content_bytes = json.dumps(self.to_dict(), indent=2).encode("utf-8")
        target.write_bytes(content_bytes)
        file_hash = hashlib.sha256(content_bytes).hexdigest()

        # Research copy
        art_dir = project_paths.artifacts_datasets
        art_dir.mkdir(parents=True, exist_ok=True)
        art_target = art_dir / target.name
        shutil.copy2(target, art_target)

        return target, file_hash

