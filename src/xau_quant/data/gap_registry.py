"""Persistent Gap Registry tracking missing market data intervals with formal categorization."""

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from xau_quant.common.paths import project_paths


class GapCategory(str, Enum):
    """Categorization taxonomy for detected market data gaps."""

    UNKNOWN = "UNKNOWN"
    ACQUISITION_FAILURE = "ACQUISITION_FAILURE"
    PROVIDER_GAP = "PROVIDER_GAP"
    EXCHANGE_MAINTENANCE_CONFIRMED = "EXCHANGE_MAINTENANCE_CONFIRMED"


class GapRecord(BaseModel):
    """Structured record capturing a single continuous gap in market data."""

    model_config = ConfigDict(frozen=True)

    gap_id: str
    instrument: str
    venue: str
    timeframe: str
    expected_start_utc: datetime
    expected_end_utc: datetime
    actual_missing_start_utc: datetime
    actual_missing_end_utc: datetime
    duration_seconds: int
    missing_candles_count: int
    detected_at_utc: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    acquisition_source: str
    category: GapCategory = GapCategory.UNKNOWN
    evidence: str = ""
    is_resolved: bool = False
    resolution_notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "instrument": self.instrument,
            "venue": self.venue,
            "timeframe": self.timeframe,
            "expected_start_utc": self.expected_start_utc.isoformat(),
            "expected_end_utc": self.expected_end_utc.isoformat(),
            "actual_missing_start_utc": self.actual_missing_start_utc.isoformat(),
            "actual_missing_end_utc": self.actual_missing_end_utc.isoformat(),
            "duration_seconds": self.duration_seconds,
            "missing_candles_count": self.missing_candles_count,
            "detected_at_utc": self.detected_at_utc.isoformat(),
            "acquisition_source": self.acquisition_source,
            "category": self.category.value,
            "evidence": self.evidence,
            "is_resolved": self.is_resolved,
            "resolution_notes": self.resolution_notes,
        }


class GapRegistry:
    """Manages atomic persistence and querying of the market data Gap Registry."""

    def __init__(self, registry_path: Optional[Path] = None) -> None:
        if registry_path is None:
            gap_dir = project_paths.data_metadata / "gap_registry"
            gap_dir.mkdir(parents=True, exist_ok=True)
            self.registry_path = gap_dir / "binance_spot_btcusdt_gaps.json"
        else:
            self.registry_path = registry_path
            self.registry_path.parent.mkdir(parents=True, exist_ok=True)

        self._gaps: Dict[str, GapRecord] = {}
        self.load()

    @property
    def total_gaps(self) -> int:
        return len(self._gaps)

    @property
    def total_missing_candles(self) -> int:
        return sum(g.missing_candles_count for g in self._gaps.values())

    def load(self) -> None:
        """Load existing gap records from disk."""
        if not self.registry_path.exists():
            return

        try:
            content = self.registry_path.read_text(encoding="utf-8")
            data = json.loads(content)
            for item in data.get("gaps", []):
                record = GapRecord(
                    gap_id=item["gap_id"],
                    instrument=item["instrument"],
                    venue=item["venue"],
                    timeframe=item["timeframe"],
                    expected_start_utc=datetime.fromisoformat(
                        item["expected_start_utc"]
                    ),
                    expected_end_utc=datetime.fromisoformat(item["expected_end_utc"]),
                    actual_missing_start_utc=datetime.fromisoformat(
                        item["actual_missing_start_utc"]
                    ),
                    actual_missing_end_utc=datetime.fromisoformat(
                        item["actual_missing_end_utc"]
                    ),
                    duration_seconds=item["duration_seconds"],
                    missing_candles_count=item["missing_candles_count"],
                    detected_at_utc=datetime.fromisoformat(item["detected_at_utc"]),
                    acquisition_source=item["acquisition_source"],
                    category=GapCategory(item["category"]),
                    evidence=item.get("evidence", ""),
                    is_resolved=item.get("is_resolved", False),
                    resolution_notes=item.get("resolution_notes"),
                )
                self._gaps[record.gap_id] = record
        except Exception:
            # Corrupted registry recovery: keep empty
            pass

    def save(self) -> None:
        """Atomically persist gap registry to disk."""
        sorted_gaps = sorted(
            self._gaps.values(), key=lambda g: g.actual_missing_start_utc
        )
        payload = {
            "schema_version": "1.1.0",
            "last_updated_utc": datetime.now(timezone.utc).isoformat(),
            "total_gaps_count": len(sorted_gaps),
            "total_missing_candles": sum(
                g.missing_candles_count for g in sorted_gaps
            ),
            "gaps": [g.to_dict() for g in sorted_gaps],
        }

        tmp_path = self.registry_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp_path.replace(self.registry_path)

    def register_gap(self, record: GapRecord) -> None:
        """Register or update a gap record and persist."""
        self._gaps[record.gap_id] = record
        self.save()

    def get_gap(self, gap_id: str) -> Optional[GapRecord]:
        return self._gaps.get(gap_id)

    def get_all_gaps(self) -> List[GapRecord]:
        return sorted(
            self._gaps.values(), key=lambda g: g.actual_missing_start_utc
        )

    def get_unresolved_gaps(self) -> List[GapRecord]:
        return [g for g in self.get_all_gaps() if not g.is_resolved]

    def to_summary_dict(self) -> Dict[str, Any]:
        all_gaps = self.get_all_gaps()
        return {
            "registry_path": str(self.registry_path),
            "total_gaps_count": len(all_gaps),
            "total_missing_candles": sum(
                g.missing_candles_count for g in all_gaps
            ),
            "unresolved_gaps_count": len(self.get_unresolved_gaps()),
            "by_category": {
                cat.value: sum(1 for g in all_gaps if g.category == cat)
                for cat in GapCategory
            },
        }
