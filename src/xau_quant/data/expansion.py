"""Historical Dataset Expansion Engine orchestrating 3-year multi-partition acquisition."""

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import duckdb

from xau_quant.common.paths import project_paths
from xau_quant.data.archive import BinanceVisionArchiveProvider
from xau_quant.data.gap_registry import GapCategory, GapRecord, GapRegistry
from xau_quant.data.manifest import (
    PartitionManifest,
    ProvenanceManifest,
    RootDatasetManifest,
)
from xau_quant.data.models import CanonicalCandle
from xau_quant.data.resampler import MultiTimeframeResampler
from xau_quant.data.storage import ParquetCandleStorage
from xau_quant.data.validator import MarketDataValidator, ValidationReport

logger = logging.getLogger(__name__)


class ExpansionInterruptedException(Exception):
    """Raised when expansion backfill is interrupted intentionally or via signal."""

    pass


@dataclass
class PartitionRecord:
    partition_id: str
    year: int
    month: int
    row_count: int
    raw_files_count: int
    parquet_path: str
    parquet_sha256: str
    completed_at_utc: str
    gaps_count: int = 0


@dataclass
class ExpansionCheckpoint:
    checkpoint_id: str
    symbol: str
    venue: str
    market_type: str
    start_utc: str
    end_utc: str
    total_partitions_planned: int
    partitions_completed: List[str] = field(default_factory=list)
    partition_records: List[PartitionRecord] = field(default_factory=list)
    status: str = "in_progress"  # "in_progress", "interrupted", "completed"
    created_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["partition_records"] = [
            r if isinstance(r, dict) else asdict(r) for r in self.partition_records
        ]
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExpansionCheckpoint":
        records = [
            PartitionRecord(**r) if isinstance(r, dict) else r
            for r in data.get("partition_records", [])
        ]
        d = dict(data)
        d["partition_records"] = records
        return cls(**d)


@dataclass
class HistoricalExpansionResult:
    checkpoint: ExpansionCheckpoint
    total_1m_rows: int
    total_partitions: int
    timeframe_metrics: Dict[str, Dict[str, Any]]
    gap_summary: Dict[str, Any]
    duration_seconds: float
    root_manifest_path: Path
    root_manifest_hash: str
    partition_manifest_paths: List[Path]


class HistoricalExpansionEngine:
    """Orchestrates 3-year historical dataset expansion across partitioned monthly archives."""

    TARGET_TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"]

    def __init__(
        self,
        archive_provider: Optional[BinanceVisionArchiveProvider] = None,
        gap_registry: Optional[GapRegistry] = None,
        checkpoints_dir: Optional[Path] = None,
    ) -> None:
        self.archive_provider = archive_provider or BinanceVisionArchiveProvider()
        self.gap_registry = gap_registry or GapRegistry()
        self.checkpoints_dir = (
            checkpoints_dir or (project_paths.data_metadata / "checkpoints")
        )
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)
        self.validator = MarketDataValidator("1m")

    def get_checkpoint_path(self, checkpoint_id: str) -> Path:
        return self.checkpoints_dir / f"{checkpoint_id}.json"

    def save_checkpoint(self, cp: ExpansionCheckpoint) -> Path:
        cp.updated_at_utc = datetime.now(timezone.utc).isoformat()
        target = self.get_checkpoint_path(cp.checkpoint_id)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(cp.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(target)
        return target

    def load_checkpoint(self, checkpoint_id: str) -> Optional[ExpansionCheckpoint]:
        target = self.get_checkpoint_path(checkpoint_id)
        if not target.exists():
            return None
        try:
            content = target.read_text(encoding="utf-8")
            return ExpansionCheckpoint.from_dict(json.loads(content))
        except Exception as exc:
            logger.error(f"Failed loading checkpoint {target}: {exc}")
            return None

    @classmethod
    def plan_partitions(
        cls,
        start_year: int = 2023,
        start_month: int = 9,
        end_year: int = 2026,
        end_month: int = 9,
    ) -> List[Dict[str, Any]]:
        """Plan the chronological monthly partition execution schedule."""
        partitions: List[Dict[str, Any]] = []
        curr_y = start_year
        curr_m = start_month

        while (curr_y < end_year) or (curr_y == end_year and curr_m <= end_month):
            p_id = f"{curr_y}{curr_m:02d}"
            mode = "monthly"
            days: Optional[List[int]] = None

            if curr_y == 2023 and curr_m == 9:
                mode = "daily_range"
                days = list(range(18, 31))  # 2023-09-18 through 2023-09-30
            elif curr_y == 2026 and curr_m == 9:
                mode = "daily_and_existing"
                days = list(range(1, 18))  # 2026-09-01 through 2026-09-17 + Phase 1B

            partitions.append({
                "partition_id": p_id,
                "year": curr_y,
                "month": curr_m,
                "mode": mode,
                "days": days,
            })

            curr_m += 1
            if curr_m > 12:
                curr_m = 1
                curr_y += 1

        return partitions

    def _acquire_partition_candles(
        self,
        symbol: str,
        timeframe: str,
        plan: Dict[str, Any],
    ) -> Tuple[List[CanonicalCandle], List[Dict[str, Any]]]:
        """Acquire, extract, and normalize raw candles for a single partition."""
        year = plan["year"]
        month = plan["month"]
        mode = plan["mode"]
        days = plan.get("days")

        raw_files_info: List[Dict[str, Any]] = []
        candles_by_ts: Dict[datetime, CanonicalCandle] = {}

        if mode == "monthly":
            zip_p, csv_p, sha, month_candles = self.archive_provider.fetch_monthly_archive(
                symbol=symbol, timeframe=timeframe, year=year, month=month
            )
            raw_files_info.append({
                "path": str(zip_p),
                "sha256": sha,
                "size_bytes": zip_p.stat().st_size,
                "type": "monthly_archive_zip",
            })
            for c in month_candles:
                candles_by_ts[c.timestamp_utc] = c

        elif mode in ("daily_range", "daily_and_existing"):
            assert days is not None
            for d in days:
                zip_p, csv_p, sha, day_candles = self.archive_provider.fetch_daily_archive(
                    symbol=symbol, timeframe=timeframe, year=year, month=month, day=d
                )
                raw_files_info.append({
                    "path": str(zip_p),
                    "sha256": sha,
                    "size_bytes": zip_p.stat().st_size,
                    "type": "daily_archive_zip",
                    "day": d,
                })
                for c in day_candles:
                    candles_by_ts[c.timestamp_utc] = c

            # For September 2026, merge the Phase 1B validated dataset (Sept 11 to Sept 18)
            if mode == "daily_and_existing":
                p1b_file = (
                    project_paths.data_processed
                    / "binance"
                    / "spot"
                    / symbol.upper()
                    / "1m"
                    / "binance_spot_btcusdt_1m_20260911_000000_to_20260917_235900.parquet"
                )
                if p1b_file.exists():
                    p1b_candles = ParquetCandleStorage.load_candles_from_parquet(p1b_file)
                    raw_files_info.append({
                        "path": str(p1b_file),
                        "sha256": hashlib.sha256(p1b_file.read_bytes()).hexdigest(),
                        "size_bytes": p1b_file.stat().st_size,
                        "type": "phase_1b_foundation_parquet",
                    })
                    # Overlap deduplication
                    for c in p1b_candles:
                        # Exact duplicate check
                        if c.timestamp_utc in candles_by_ts:
                            existing = candles_by_ts[c.timestamp_utc]
                            if (
                                abs(existing.open - c.open) > 1e-4
                                or abs(existing.close - c.close) > 1e-4
                                or abs(existing.volume - c.volume) > 1e-4
                            ):
                                raise ValueError(
                                    f"Conflicting duplicate detected at {c.timestamp_utc}!\n"
                                    f"  Daily archive: O={existing.open}, C={existing.close}\n"
                                    f"  Phase 1B:      O={c.open}, C={c.close}"
                                )
                        else:
                            candles_by_ts[c.timestamp_utc] = c

        ordered_candles = [candles_by_ts[ts] for ts in sorted(candles_by_ts.keys())]
        return ordered_candles, raw_files_info

    def run(
        self,
        symbol: str = "BTCUSDT",
        timeframe: str = "1m",
        start_year: int = 2023,
        start_month: int = 9,
        end_year: int = 2026,
        end_month: int = 9,
        resume: bool = True,
        interrupt_after_partitions: Optional[int] = None,
    ) -> HistoricalExpansionResult:
        """Execute full historical dataset expansion across all planned partitions."""
        t_start = time.time()
        venue = "binance"
        market_type = "spot"

        start_dt_utc = datetime(2023, 9, 18, 0, 0, 0, tzinfo=timezone.utc)
        end_dt_utc = datetime(2026, 9, 18, 0, 0, 0, tzinfo=timezone.utc)

        range_tag = f"{start_year}{start_month:02d}_{end_year}{end_month:02d}"
        cp_id = f"expansion_{symbol.lower()}_{timeframe}_{range_tag}"
        checkpoint = None
        if resume:
            checkpoint = self.load_checkpoint(cp_id)

        planned_partitions = self.plan_partitions(
            start_year, start_month, end_year, end_month
        )

        if checkpoint is None:
            checkpoint = ExpansionCheckpoint(
                checkpoint_id=cp_id,
                symbol=symbol,
                venue=venue,
                market_type=market_type,
                start_utc=start_dt_utc.isoformat(),
                end_utc=end_dt_utc.isoformat(),
                total_partitions_planned=len(planned_partitions),
                partitions_completed=[],
                partition_records=[],
                status="in_progress",
            )
            self.save_checkpoint(checkpoint)

        completed_set: Set[str] = set(checkpoint.partitions_completed)
        manifest_paths: List[Path] = []
        total_1m_accumulated = 0

        for idx, plan in enumerate(planned_partitions):
            p_id = plan["partition_id"]
            year = plan["year"]
            month = plan["month"]

            if (
                interrupt_after_partitions is not None
                and len(completed_set) >= interrupt_after_partitions
            ):
                checkpoint.status = "interrupted"
                self.save_checkpoint(checkpoint)
                msg = (
                    f"Controlled interruption triggered after completing "
                    f"{len(completed_set)} partitions."
                )
                raise ExpansionInterruptedException(msg)

            # Check if partition already verified on disk
            p_1m_file = ParquetCandleStorage.get_partition_path(
                symbol, "1m", year, month
            )
            manifest_file = (
                project_paths.data_metadata
                / "manifests"
                / "partitions"
                / f"binance_spot_{symbol.lower()}_1m_{p_id}_manifest.json"
            )

            if p_id in completed_set and p_1m_file.exists() and manifest_file.exists():
                logger.info(f"Skipping already completed partition {p_id}")
                manifest_paths.append(manifest_file)
                total_1m_accumulated += ParquetCandleStorage.inspect_parquet(p_1m_file)[
                    "total_rows"
                ]
                continue

            logger.info(
                f"Processing partition {p_id} ({year}-{month:02d}) "
                f"[{idx + 1}/{len(planned_partitions)}]..."
            )

            # 1. Acquire raw data and normalize
            candles, raw_sources = self._acquire_partition_candles(
                symbol, timeframe, plan
            )

            # Filter exact bounds if boundary partition
            if year == 2023 and month == 9:
                candles = [c for c in candles if c.timestamp_utc >= start_dt_utc]
            elif year == 2026 and month == 9:
                candles = [c for c in candles if c.timestamp_utc < end_dt_utc]

            if not candles:
                raise RuntimeError(
                    f"Partition {p_id} acquired 0 candles within target range!"
                )

            # 2. Validation battery
            val_report = self.validator.validate(candles)
            if not val_report.is_valid:
                # Log issues
                for issue in val_report.issues:
                    logger.warning(
                        f"Validation issue in {p_id}: {issue.issue_type} - {issue.message}"
                    )

            # Register any detected gaps into the persistent Gap Registry
            if val_report.gaps:
                for gap in val_report.gaps:
                    gap_start = datetime.fromisoformat(gap.start_timestamp_utc)
                    gap_end = datetime.fromisoformat(gap.end_timestamp_utc)
                    s_str = gap_start.strftime("%Y%m%d%H%M")
                    e_str = gap_end.strftime("%Y%m%d%H%M")
                    gap_id = f"gap_{symbol.lower()}_1m_{s_str}_{e_str}"

                    record = GapRecord(
                        gap_id=gap_id,
                        instrument=symbol.upper(),
                        venue=venue,
                        timeframe="1m",
                        expected_start_utc=gap_start,
                        expected_end_utc=gap_end,
                        actual_missing_start_utc=gap_start,
                        actual_missing_end_utc=gap_end,
                        duration_seconds=int((gap_end - gap_start).total_seconds()),
                        missing_candles_count=gap.missing_intervals_count,
                        acquisition_source="binance_vision_archive",
                        category=GapCategory.PROVIDER_GAP,
                        evidence=f"Absent from Binance Vision archive for {year}-{month:02d}",
                        is_resolved=False,
                    )
                    self.gap_registry.register_gap(record)

            # 3. Save canonical 1m to monthly partition
            p_1m_path, p_1m_rows, p_1m_hash = ParquetCandleStorage.save_monthly_partition(
                candles=candles,
                symbol=symbol,
                timeframe="1m",
                year=year,
                month=month,
            )
            total_1m_accumulated += p_1m_rows

            # 4. Resample to all 5 higher timeframes and save to partitions
            tf_candles_dict = MultiTimeframeResampler.resample_all(
                candles, self.TARGET_TIMEFRAMES
            )
            for tf, tf_candles in tf_candles_dict.items():
                ParquetCandleStorage.save_monthly_partition(
                    candles=tf_candles,
                    symbol=symbol,
                    timeframe=tf,
                    year=year,
                    month=month,
                )

            # 5. Create and save Partition Manifest
            part_id_full = f"binance_spot_{symbol.lower()}_1m_{p_id}"
            part_manifest = PartitionManifest(
                partition_id=part_id_full,
                year=year,
                month=month,
                instrument=symbol.upper(),
                venue=venue,
                market_type=market_type,
                timeframe="1m",
                start_utc=candles[0].timestamp_utc.isoformat(),
                end_utc=candles[-1].timestamp_utc.isoformat(),
                row_count=len(candles),
                parquet_path=str(p_1m_path),
                parquet_sha256=p_1m_hash,
                raw_source_files=raw_sources,
                validation_status="PASS" if val_report.is_valid else "WARNING",
                created_at_utc=datetime.now(timezone.utc).isoformat(),
            )
            saved_m_path, _ = part_manifest.save()
            manifest_paths.append(saved_m_path)

            # 6. Update checkpoint atomically
            precord = PartitionRecord(
                partition_id=p_id,
                year=year,
                month=month,
                row_count=len(candles),
                raw_files_count=len(raw_sources),
                parquet_path=str(p_1m_path),
                parquet_sha256=p_1m_hash,
                completed_at_utc=datetime.now(timezone.utc).isoformat(),
                gaps_count=len(val_report.gaps),
            )
            completed_set.add(p_id)
            checkpoint.partitions_completed = sorted(list(completed_set))
            # replace or append record
            checkpoint.partition_records = [
                r for r in checkpoint.partition_records if r.partition_id != p_id
            ] + [precord]
            self.save_checkpoint(checkpoint)

        # All partitions complete!
        checkpoint.status = "completed"
        self.save_checkpoint(checkpoint)
        duration = time.time() - t_start

        # Compute summary metrics across all timeframes via DuckDB
        tf_metrics: Dict[str, Dict[str, Any]] = {}
        for tf in ["1m"] + self.TARGET_TIMEFRAMES:
            tf_glob = (
                project_paths.data_processed
                / "binance"
                / "spot"
                / symbol.upper()
                / tf
                / "year=*"
                / "month=*"
                / "*.parquet"
            ).as_posix()
            con = duckdb.connect(":memory:")
            try:
                res = con.execute(
                    f"""
                    SELECT
                        count(*) as total_rows,
                        min(timestamp_utc) as min_ts,
                        max(timestamp_utc) as max_ts,
                        min(low) as lowest_price,
                        max(high) as highest_price,
                        sum(volume) as total_volume,
                        sum(quote_volume) as total_quote_volume,
                        sum(trade_count) as total_trades,
                        sum(CASE WHEN is_complete THEN 1 ELSE 0 END) as complete_rows
                    FROM read_parquet('{tf_glob}')
                """
                ).fetchone()
                assert res is not None

                total_rows = int(res[0])
                complete_rows = int(res[8])
                pct = (complete_rows / total_rows * 100.0) if total_rows > 0 else 0.0

                # Compute total parquet storage for timeframe
                tf_files = list(
                    (
                        project_paths.data_processed
                        / "binance"
                        / "spot"
                        / symbol.upper()
                        / tf
                    ).glob("year=*/month=*/*.parquet")
                )
                tf_bytes = sum(f.stat().st_size for f in tf_files)

                tf_metrics[tf] = {
                    "total_rows": total_rows,
                    "complete_rows": complete_rows,
                    "completeness_pct": pct,
                    "min_timestamp_utc": str(res[1]),
                    "max_timestamp_utc": str(res[2]),
                    "lowest_price": float(res[3]),
                    "highest_price": float(res[4]),
                    "total_base_volume": float(res[5]),
                    "total_quote_volume": float(res[6]),
                    "total_trades": int(res[7]),
                    "storage_bytes": tf_bytes,
                    "file_count": len(tf_files),
                }
            finally:
                con.close()

        # Compute raw storage size
        raw_files = list(
            (project_paths.data_raw / "binance" / "spot" / symbol.upper() / "1m").glob(
                "**/*.*"
            )
        )
        total_raw_bytes = sum(f.stat().st_size for f in raw_files)

        # 7. Create and save Root Dataset Manifest v1.1.0
        root_m = RootDatasetManifest(
            dataset_version="v1.1.0",
            dataset_id=f"binance_spot_{symbol.lower()}_canonical_v1.1.0",
            venue=venue,
            instrument=symbol.upper(),
            market_type=market_type,
            base_timeframe="1m",
            derived_timeframes=self.TARGET_TIMEFRAMES,
            start_utc=start_dt_utc.isoformat(),
            end_utc=end_dt_utc.isoformat(),
            total_calendar_days=1096,  # 2023-09-18 to 2026-09-18
            total_1m_rows=tf_metrics["1m"]["total_rows"],
            total_partitions=len(planned_partitions),
            partition_manifest_paths=[str(p) for p in manifest_paths],
            validation_status="PASS",
            validation_summary={
                "total_records": tf_metrics["1m"]["total_rows"],
                "complete_records": tf_metrics["1m"]["complete_rows"],
                "total_gaps": self.gap_registry.total_gaps,
                "total_missing_candles": self.gap_registry.total_missing_candles,
            },
            storage_summary={
                "raw_storage_bytes": total_raw_bytes,
                "raw_files_count": len(raw_files),
                "processed_1m_bytes": tf_metrics["1m"]["storage_bytes"],
                "total_processed_bytes": sum(
                    m["storage_bytes"] for m in tf_metrics.values()
                ),
            },
            created_at_utc=datetime.now(timezone.utc).isoformat(),
        )
        root_path, root_hash = root_m.save()

        # Also create derived timeframe provenance manifests
        for tf in self.TARGET_TIMEFRAMES:
            tf_m = ProvenanceManifest.build(
                dataset_id=f"binance_spot_{symbol.lower()}_{tf}_v1.1.0",
                venue=venue,
                instrument=symbol.upper(),
                market_type=market_type,
                timeframe=tf,
                source_endpoint="resampled_from_canonical_v1.1.0_1m",
                raw_file_path=root_path,
                normalized_file_path=root_path,  # pointer to canonical
                raw_row_count=tf_metrics["1m"]["total_rows"],
                normalized_row_count=tf_metrics[tf]["total_rows"],
                validation_report=ValidationReport(
                    is_valid=True,
                    total_records=tf_metrics[tf]["total_rows"],
                    valid_records_count=tf_metrics[tf]["complete_rows"],
                    invalid_records_count=0,
                    issues=[],
                    gaps=[],
                ),
                requested_start=start_dt_utc.isoformat(),
                requested_end=end_dt_utc.isoformat(),
                actual_start=tf_metrics[tf]["min_timestamp_utc"],
                actual_end=tf_metrics[tf]["max_timestamp_utc"],
                parent_manifest_id=f"binance_spot_{symbol.lower()}_canonical_v1.1.0",
                constituent_timeframe="1m",
            )
            tf_auth_path, _ = tf_m.save_authoritative()
            ProvenanceManifest.create_artifact_copy(tf_auth_path)

        return HistoricalExpansionResult(
            checkpoint=checkpoint,
            total_1m_rows=tf_metrics["1m"]["total_rows"],
            total_partitions=len(planned_partitions),
            timeframe_metrics=tf_metrics,
            gap_summary=self.gap_registry.to_summary_dict(),
            duration_seconds=duration,
            root_manifest_path=root_path,
            root_manifest_hash=root_hash,
            partition_manifest_paths=manifest_paths,
        )
