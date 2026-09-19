"""Data quality reporting engine for historical backfill and multi-timeframe datasets."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from xau_quant.data.models import CanonicalCandle
from xau_quant.data.validator import ValidationReport


@dataclass
class TimeframeQualityMetrics:
    """Quality metrics for a specific timeframe dataset."""

    timeframe: str
    total_rows: int
    complete_rows: int
    incomplete_rows: int
    completeness_percentage: float
    parquet_path: str
    parquet_size_bytes: int
    parquet_sha256: str
    min_timestamp_utc: str
    max_timestamp_utc: str
    lowest_price: float
    highest_price: float
    total_base_volume: float
    total_quote_volume: float
    total_trades: int


@dataclass
class BackfillQualitySummary:
    """Comprehensive diagnostic metrics for Phase 1B historical backfill."""

    venue: str
    instrument: str
    market_type: str
    requested_start_utc: str
    requested_end_utc: str
    actual_start_utc: str
    actual_end_utc: str
    total_chunks: int
    raw_storage_bytes: int
    raw_files_count: int
    total_1m_rows: int
    expected_1m_rows: int
    coverage_percentage: float
    validation_status: str
    valid_records_count: int
    invalid_records_count: int
    gap_count: int
    missing_candles_count: int
    duplicate_count: int
    conflicting_duplicate_count: int
    ohlc_violations_count: int
    non_positive_price_count: int
    volume_anomalies_count: int
    incomplete_1m_count: int
    acquisition_duration_seconds: float
    processing_duration_seconds: float
    timeframe_metrics: Dict[str, TimeframeQualityMetrics] = field(default_factory=dict)
    manifest_paths: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "venue": self.venue,
            "instrument": self.instrument,
            "market_type": self.market_type,
            "requested_start_utc": self.requested_start_utc,
            "requested_end_utc": self.requested_end_utc,
            "actual_start_utc": self.actual_start_utc,
            "actual_end_utc": self.actual_end_utc,
            "total_chunks": self.total_chunks,
            "raw_storage_bytes": self.raw_storage_bytes,
            "raw_files_count": self.raw_files_count,
            "total_1m_rows": self.total_1m_rows,
            "expected_1m_rows": self.expected_1m_rows,
            "coverage_percentage": self.coverage_percentage,
            "validation_status": self.validation_status,
            "valid_records_count": self.valid_records_count,
            "invalid_records_count": self.invalid_records_count,
            "gap_count": self.gap_count,
            "missing_candles_count": self.missing_candles_count,
            "duplicate_count": self.duplicate_count,
            "conflicting_duplicate_count": self.conflicting_duplicate_count,
            "ohlc_violations_count": self.ohlc_violations_count,
            "non_positive_price_count": self.non_positive_price_count,
            "volume_anomalies_count": self.volume_anomalies_count,
            "incomplete_1m_count": self.incomplete_1m_count,
            "acquisition_duration_seconds": self.acquisition_duration_seconds,
            "processing_duration_seconds": self.processing_duration_seconds,
            "timeframe_metrics": {
                tf: m.__dict__ for tf, m in self.timeframe_metrics.items()
            },
            "manifest_paths": self.manifest_paths,
        }


class DataQualityReporter:
    """Calculates verifiable dataset quality metrics across multi-timeframe series."""

    @staticmethod
    def compute_timeframe_metrics(
        candles: List[CanonicalCandle],
        timeframe: str,
        parquet_path: Path,
        parquet_sha256: str,
    ) -> TimeframeQualityMetrics:
        """Compute metrics for a single timeframe series."""
        total = len(candles)
        if total == 0:
            raise ValueError(f"Cannot compute metrics for empty timeframe {timeframe}")

        complete = sum(1 for c in candles if c.is_complete)
        incomplete = total - complete
        pct = (complete / total) * 100.0 if total > 0 else 0.0

        p_size = parquet_path.stat().st_size if parquet_path.exists() else 0

        min_ts = min(c.timestamp_utc for c in candles).isoformat()
        max_ts = max(c.timestamp_utc for c in candles).isoformat()
        low = min(c.low for c in candles)
        high = max(c.high for c in candles)
        vol = sum(c.volume for c in candles)
        qvol = sum(c.quote_volume for c in candles)
        trades = sum(c.trade_count for c in candles)

        return TimeframeQualityMetrics(
            timeframe=timeframe,
            total_rows=total,
            complete_rows=complete,
            incomplete_rows=incomplete,
            completeness_percentage=round(pct, 2),
            parquet_path=str(parquet_path),
            parquet_size_bytes=p_size,
            parquet_sha256=parquet_sha256,
            min_timestamp_utc=min_ts,
            max_timestamp_utc=max_ts,
            lowest_price=low,
            highest_price=high,
            total_base_volume=round(vol, 4),
            total_quote_volume=round(qvol, 2),
            total_trades=trades,
        )

    @classmethod
    def generate_summary(
        cls,
        venue: str,
        instrument: str,
        requested_start: datetime,
        requested_end: datetime,
        candles_1m: List[CanonicalCandle],
        validation_report: ValidationReport,
        raw_files: List[Path],
        timeframe_datasets: Dict[str, Tuple[List[CanonicalCandle], Path, str]],
        acquisition_duration: float,
        processing_duration: float,
        manifest_paths: Optional[Dict[str, str]] = None,
    ) -> BackfillQualitySummary:
        """Aggregate end-to-end metrics into authoritative summary."""
        expected_1m = int((requested_end - requested_start).total_seconds() / 60)
        actual_1m = len(candles_1m)
        coverage_pct = (actual_1m / expected_1m) * 100.0 if expected_1m > 0 else 0.0

        raw_storage = sum(f.stat().st_size for f in raw_files if f.exists())

        # Count validation issue categories
        ohlc_violations = sum(
            1 for iss in validation_report.issues if "OHLC" in iss.issue_type
        )
        non_positive = sum(
            1 for iss in validation_report.issues if iss.issue_type == "NON_POSITIVE_PRICE"
        )
        volume_anomalies = sum(
            1
            for iss in validation_report.issues
            if iss.issue_type in ("NEGATIVE_VOLUME", "TAKER_VOLUME_EXCEEDS_TOTAL")
        )
        incomplete_1m = sum(1 for c in candles_1m if not c.is_complete)
        missing_candles = sum(g.missing_intervals_count for g in validation_report.gaps)

        tf_metrics: Dict[str, TimeframeQualityMetrics] = {}
        for tf, (candles, p_path, p_hash) in timeframe_datasets.items():
            tf_metrics[tf] = cls.compute_timeframe_metrics(
                candles=candles,
                timeframe=tf,
                parquet_path=p_path,
                parquet_sha256=p_hash,
            )

        actual_start = (
            min(c.timestamp_utc for c in candles_1m).isoformat()
            if candles_1m
            else requested_start.isoformat()
        )
        actual_end = (
            max(c.timestamp_utc for c in candles_1m).isoformat()
            if candles_1m
            else requested_end.isoformat()
        )

        return BackfillQualitySummary(
            venue=venue,
            instrument=instrument,
            market_type="spot",
            requested_start_utc=requested_start.isoformat(),
            requested_end_utc=requested_end.isoformat(),
            actual_start_utc=actual_start,
            actual_end_utc=actual_end,
            total_chunks=len(raw_files),
            raw_storage_bytes=raw_storage,
            raw_files_count=len(raw_files),
            total_1m_rows=actual_1m,
            expected_1m_rows=expected_1m,
            coverage_percentage=round(coverage_pct, 4),
            validation_status="PASS" if validation_report.is_valid else "FAIL",
            valid_records_count=validation_report.valid_records_count,
            invalid_records_count=validation_report.invalid_records_count,
            gap_count=len(validation_report.gaps),
            missing_candles_count=missing_candles,
            duplicate_count=validation_report.duplicate_count,
            conflicting_duplicate_count=validation_report.conflicting_duplicate_count,
            ohlc_violations_count=ohlc_violations,
            non_positive_price_count=non_positive,
            volume_anomalies_count=volume_anomalies,
            incomplete_1m_count=incomplete_1m,
            acquisition_duration_seconds=round(acquisition_duration, 2),
            processing_duration_seconds=round(processing_duration, 2),
            timeframe_metrics=tf_metrics,
            manifest_paths=manifest_paths or {},
        )
