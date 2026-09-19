"""Historical backfill engine and checkpoint management for market data acquisition."""

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from xau_quant.common.paths import project_paths
from xau_quant.data.binance import BinanceSpotProvider
from xau_quant.data.models import CanonicalCandle
from xau_quant.data.normalizer import BinanceKlineNormalizer
from xau_quant.data.provider import DataProvider
from xau_quant.data.validator import MarketDataValidator, ValidationReport

logger = logging.getLogger(__name__)


class BackfillInterruptedException(Exception):
    """Raised when backfill execution is intentionally paused or interrupted."""

    pass


@dataclass
class ChunkRecord:
    """Metadata tracking a single historical acquisition chunk."""

    chunk_index: int
    start_time_ms: int
    end_time_ms: int
    start_time_utc: str
    end_time_utc: str
    records_acquired: int
    raw_file_path: str
    raw_file_sha256: str
    completed_at_utc: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BackfillCheckpoint:
    """Durable state tracking historical backfill execution and progress."""

    checkpoint_id: str
    venue: str
    instrument: str
    market_type: str
    timeframe: str
    requested_start_utc: str
    requested_end_utc: str
    total_chunks_planned: int
    chunks_completed: int
    completed_until_utc: Optional[str]
    status: str  # "in_progress", "interrupted", "completed", "failed"
    chunks: List[ChunkRecord] = field(default_factory=list)
    last_error: Optional[str] = None
    created_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["chunks"] = [c if isinstance(c, dict) else c.to_dict() for c in self.chunks]
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BackfillCheckpoint":
        chunks_data = data.get("chunks", [])
        parsed_chunks = [
            ChunkRecord(**c) if isinstance(c, dict) else c for c in chunks_data
        ]
        data_copy = dict(data)
        data_copy["chunks"] = parsed_chunks
        return cls(**data_copy)


class CheckpointManager:
    """Manages atomic persistence and recovery of backfill checkpoints."""

    def __init__(self, checkpoints_dir: Optional[Path] = None) -> None:
        self.checkpoints_dir = (
            checkpoints_dir or (project_paths.data_metadata / "checkpoints")
        )
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)

    def get_checkpoint_path(self, checkpoint_id: str) -> Path:
        return self.checkpoints_dir / f"{checkpoint_id}.json"

    def save_checkpoint(self, checkpoint: BackfillCheckpoint) -> Path:
        """Atomically persist checkpoint state to disk."""
        checkpoint.updated_at_utc = datetime.now(timezone.utc).isoformat()
        final_path = self.get_checkpoint_path(checkpoint.checkpoint_id)
        tmp_path = self.checkpoints_dir / f"{checkpoint.checkpoint_id}.tmp"

        payload = json.dumps(checkpoint.to_dict(), indent=2).encode("utf-8")
        tmp_path.write_bytes(payload)
        tmp_path.replace(final_path)
        logger.debug(f"Saved checkpoint atomically to {final_path}")
        return final_path

    def load_checkpoint(self, checkpoint_id: str) -> Optional[BackfillCheckpoint]:
        """Load checkpoint state if exists."""
        target_path = self.get_checkpoint_path(checkpoint_id)
        if not target_path.exists():
            return None
        try:
            content = target_path.read_bytes().decode("utf-8")
            data = json.loads(content)
            return BackfillCheckpoint.from_dict(data)
        except Exception as exc:
            logger.error(f"Failed loading checkpoint from {target_path}: {exc}")
            raise RuntimeError(f"Corrupt checkpoint file {target_path}: {exc}") from exc

    def find_checkpoint(
        self,
        venue: str,
        instrument: str,
        timeframe: str,
        start_utc: str,
        end_utc: str,
    ) -> Optional[BackfillCheckpoint]:
        """Find an existing checkpoint matching the specified parameters."""
        for file in self.checkpoints_dir.glob("*.json"):
            try:
                data = json.loads(file.read_bytes().decode("utf-8"))
                if (
                    data.get("venue") == venue.lower()
                    and data.get("instrument") == instrument.upper()
                    and data.get("timeframe") == timeframe
                    and data.get("requested_start_utc") == start_utc
                    and data.get("requested_end_utc") == end_utc
                ):
                    return BackfillCheckpoint.from_dict(data)
            except Exception:
                continue
        return None


@dataclass
class BackfillResult:
    """Execution report containing acquired candles, validation report, and lineage."""

    checkpoint: BackfillCheckpoint
    candles: List[CanonicalCandle]
    validation_report: ValidationReport
    raw_files: List[Path]
    total_records: int
    duration_seconds: float
    is_complete: bool


class BackfillEngine:
    """Production-oriented historical backfill runner with chunking, rate limiting, and resume."""

    TIMEFRAME_MS_MAP = {
        "1m": 60_000,
        "3m": 180_000,
        "5m": 300_000,
        "15m": 900_000,
        "30m": 1_800_000,
        "1h": 3_600_000,
        "2h": 7_200_000,
        "4h": 14_400_000,
        "1d": 86_400_000,
    }

    def __init__(
        self,
        provider: Optional[DataProvider] = None,
        checkpoint_manager: Optional[CheckpointManager] = None,
        rate_limit_delay_seconds: float = 0.1,
        max_retries: int = 5,
    ) -> None:
        self.provider = provider or BinanceSpotProvider()
        self.checkpoint_manager = checkpoint_manager or CheckpointManager()
        self.rate_limit_delay = rate_limit_delay_seconds
        self.max_retries = max_retries

    @classmethod
    def generate_checkpoint_id(
        cls,
        venue: str,
        instrument: str,
        timeframe: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> str:
        s_str = start_utc.strftime("%Y%m%d%H%M")
        e_str = end_utc.strftime("%Y%m%d%H%M")
        return f"backfill_{venue.lower()}_{instrument.lower()}_{timeframe}_{s_str}_{e_str}"

    @classmethod
    def plan_chunks(
        cls,
        start_utc: datetime,
        end_utc: datetime,
        timeframe: str = "1m",
        chunk_limit: int = 1000,
    ) -> List[Tuple[int, int, datetime, datetime]]:
        """Calculate deterministic contiguous chunk windows.

        Returns list of (start_ms, end_ms, start_dt, end_dt).
        """
        step_ms = cls.TIMEFRAME_MS_MAP.get(timeframe, 60_000)
        start_ms = int(start_utc.timestamp() * 1000)
        end_ms = int(end_utc.timestamp() * 1000)

        if end_ms <= start_ms:
            raise ValueError(
                f"end_utc ({end_utc.isoformat()}) must be strictly "
                f"after start_utc ({start_utc.isoformat()})"
            )

        chunks: List[Tuple[int, int, datetime, datetime]] = []
        curr_start_ms = start_ms

        while curr_start_ms < end_ms:
            chunk_intervals = min(chunk_limit, (end_ms - curr_start_ms + step_ms - 1) // step_ms)
            curr_end_ms = min(end_ms - 1, curr_start_ms + chunk_intervals * step_ms - 1)

            c_start_dt = datetime.fromtimestamp(curr_start_ms / 1000.0, tz=timezone.utc)
            c_end_dt = datetime.fromtimestamp(
                (curr_start_ms + chunk_intervals * step_ms) / 1000.0, tz=timezone.utc
            )

            chunks.append((curr_start_ms, curr_end_ms, c_start_dt, c_end_dt))
            curr_start_ms += chunk_intervals * step_ms

        return chunks

    def _fetch_chunk_with_retry(
        self,
        symbol: str,
        timeframe: str,
        start_ms: int,
        end_ms: int,
        limit: int,
    ) -> Tuple[Path, bytes, Dict[str, Any]]:
        """Fetch a single chunk with exponential backoff and rate limit handling."""
        attempt = 0
        backoff = 1.0

        while attempt < self.max_retries:
            attempt += 1
            try:
                raw_path, raw_bytes, meta = self.provider.fetch_historical_raw(
                    symbol=symbol,
                    interval=timeframe,
                    start_time_ms=start_ms,
                    end_time_ms=end_ms,
                    limit=limit,
                )
                if self.rate_limit_delay > 0:
                    time.sleep(self.rate_limit_delay)
                return raw_path, raw_bytes, meta
            except Exception as exc:
                err_str = str(exc)
                logger.warning(
                    f"Chunk request failed (attempt {attempt}/{self.max_retries}) "
                    f"for {symbol} {start_ms}-{end_ms}: {err_str}"
                )
                if attempt >= self.max_retries:
                    raise RuntimeError(
                        f"Max retries exceeded fetching {symbol} {timeframe} "
                        f"({start_ms}-{end_ms}): {err_str}"
                    ) from exc
                time.sleep(backoff)
                backoff *= 2.0

        raise RuntimeError("Unexpected failure in _fetch_chunk_with_retry")

    def run(
        self,
        symbol: str = "BTCUSDT",
        timeframe: str = "1m",
        start_utc: Optional[datetime] = None,
        end_utc: Optional[datetime] = None,
        chunk_limit: int = 1000,
        resume: bool = True,
        interrupt_after_chunks: Optional[int] = None,
    ) -> BackfillResult:
        """Execute historical backfill runner with durable checkpointing and resume support."""
        if start_utc is None or end_utc is None:
            raise ValueError("start_utc and end_utc are required")

        if start_utc.tzinfo is None:
            start_utc = start_utc.replace(tzinfo=timezone.utc)
        else:
            start_utc = start_utc.astimezone(timezone.utc)

        if end_utc.tzinfo is None:
            end_utc = end_utc.replace(tzinfo=timezone.utc)
        else:
            end_utc = end_utc.astimezone(timezone.utc)

        t_start = time.time()
        venue = self.provider.venue_name
        checkpoint_id = self.generate_checkpoint_id(
            venue=venue,
            instrument=symbol,
            timeframe=timeframe,
            start_utc=start_utc,
            end_utc=end_utc,
        )

        planned_chunks = self.plan_chunks(
            start_utc=start_utc,
            end_utc=end_utc,
            timeframe=timeframe,
            chunk_limit=chunk_limit,
        )

        checkpoint: Optional[BackfillCheckpoint] = None
        if resume:
            checkpoint = self.checkpoint_manager.load_checkpoint(checkpoint_id)
            if checkpoint is not None:
                logger.info(
                    f"Resuming backfill from existing checkpoint {checkpoint_id} "
                    f"({checkpoint.chunks_completed}/{checkpoint.total_chunks_planned} completed)"
                )

        if checkpoint is None:
            checkpoint = BackfillCheckpoint(
                checkpoint_id=checkpoint_id,
                venue=venue,
                instrument=symbol.upper(),
                market_type="spot",
                timeframe=timeframe,
                requested_start_utc=start_utc.isoformat(),
                requested_end_utc=end_utc.isoformat(),
                total_chunks_planned=len(planned_chunks),
                chunks_completed=0,
                completed_until_utc=None,
                status="in_progress",
                chunks=[],
            )
            self.checkpoint_manager.save_checkpoint(checkpoint)

        completed_chunk_indices = {chk.chunk_index for chk in checkpoint.chunks}

        for chk in checkpoint.chunks:
            p = Path(chk.raw_file_path)
            if not p.exists():
                logger.warning(
                    f"Raw chunk file missing for chunk {chk.chunk_index}: {p}. Will re-fetch."
                )
                completed_chunk_indices.remove(chk.chunk_index)

        all_raw_files: List[Path] = [
            Path(chk.raw_file_path)
            for chk in checkpoint.chunks
            if chk.chunk_index in completed_chunk_indices
        ]

        try:
            for idx, (c_start_ms, c_end_ms, c_start_dt, c_end_dt) in enumerate(planned_chunks):
                if idx in completed_chunk_indices:
                    logger.debug(
                        f"Skipping already completed chunk {idx + 1}/{len(planned_chunks)}"
                    )
                    continue

                logger.info(
                    f"Acquiring chunk {idx + 1}/{len(planned_chunks)}: "
                    f"{c_start_dt.isoformat()} to {c_end_dt.isoformat()}"
                )

                raw_path, raw_bytes, meta = self._fetch_chunk_with_retry(
                    symbol=symbol,
                    timeframe=timeframe,
                    start_ms=c_start_ms,
                    end_ms=c_end_ms,
                    limit=chunk_limit,
                )

                chunk_record = ChunkRecord(
                    chunk_index=idx,
                    start_time_ms=c_start_ms,
                    end_time_ms=c_end_ms,
                    start_time_utc=c_start_dt.isoformat(),
                    end_time_utc=c_end_dt.isoformat(),
                    records_acquired=meta["actual_records"],
                    raw_file_path=str(raw_path),
                    raw_file_sha256=meta["sha256"],
                    completed_at_utc=datetime.now(timezone.utc).isoformat(),
                )

                checkpoint.chunks.append(chunk_record)
                checkpoint.chunks_completed = len(checkpoint.chunks)
                checkpoint.completed_until_utc = c_end_dt.isoformat()
                all_raw_files.append(raw_path)

                self.checkpoint_manager.save_checkpoint(checkpoint)

                if (
                    interrupt_after_chunks is not None
                    and checkpoint.chunks_completed >= interrupt_after_chunks
                    and checkpoint.chunks_completed < len(planned_chunks)
                ):
                    checkpoint.status = "interrupted"
                    self.checkpoint_manager.save_checkpoint(checkpoint)
                    logger.info(
                        f"Backfill interrupted after {checkpoint.chunks_completed} chunks."
                    )
                    raise BackfillInterruptedException(
                        f"Backfill paused after {checkpoint.chunks_completed} chunks "
                        f"(checkpoint: {checkpoint_id})"
                    )

            checkpoint.status = "completed"
            self.checkpoint_manager.save_checkpoint(checkpoint)

        except BackfillInterruptedException:
            raise
        except Exception as exc:
            checkpoint.status = "failed"
            checkpoint.last_error = str(exc)
            self.checkpoint_manager.save_checkpoint(checkpoint)
            raise

        all_candles: List[CanonicalCandle] = []
        for raw_file in all_raw_files:
            raw_data = raw_file.read_bytes()
            chunk_candles = BinanceKlineNormalizer.normalize_payload(
                raw_data, instrument=symbol, timeframe=timeframe
            )
            all_candles.extend(chunk_candles)

        all_candles.sort(key=lambda c: c.timestamp_utc)

        deduped_candles: List[CanonicalCandle] = []
        seen_timestamps: Dict[str, CanonicalCandle] = {}
        for c in all_candles:
            ts_str = c.timestamp_utc.isoformat()
            if ts_str in seen_timestamps:
                prior = seen_timestamps[ts_str]
                if (
                    prior.open != c.open
                    or prior.high != c.high
                    or prior.low != c.low
                    or prior.close != c.close
                    or prior.volume != c.volume
                ):
                    logger.error(
                        f"Conflicting duplicate detected at {ts_str}! "
                        f"Prior: O={prior.open} H={prior.high} L={prior.low} C={prior.close} | "
                        f"New: O={c.open} H={c.high} L={c.low} C={c.close}"
                    )
                    deduped_candles.append(c)
                else:
                    logger.debug(f"Skipping exact duplicate candle at {ts_str}")
            else:
                seen_timestamps[ts_str] = c
                deduped_candles.append(c)

        validator = MarketDataValidator(expected_timeframe=timeframe)
        validation_report = validator.validate(deduped_candles)

        elapsed = time.time() - t_start

        return BackfillResult(
            checkpoint=checkpoint,
            candles=deduped_candles,
            validation_report=validation_report,
            raw_files=all_raw_files,
            total_records=len(deduped_candles),
            duration_seconds=elapsed,
            is_complete=checkpoint.status == "completed" and validation_report.is_valid,
        )
