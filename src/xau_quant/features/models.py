"""Data models and type definitions for the market feature engine."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from pydantic import BaseModel, ConfigDict

from xau_quant.data.models import CanonicalCandle


@dataclass(frozen=True)
class ColumnSpec:
    """Explicitly typed column definition emitted by a feature."""

    name: str
    duckdb_type: str  # 'DOUBLE', 'BOOLEAN', 'TIMESTAMPTZ', 'SMALLINT', 'VARCHAR'
    nullable: bool = False  # True ONLY for event attributes (e.g. pivot timestamp & age)
    description: str = ""


@dataclass(frozen=True)
class FeatureDefinition:
    """Registry entry owning metadata and typed column specifications."""

    name: str
    family: str
    calculator: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    required_history_bars: int = 1
    columns: Tuple[ColumnSpec, ...] = field(default_factory=tuple)
    temporal_semantics: str = "point_in_time"  # 'point_in_time', 'confirmation_lag_s'
    mtf_timeframe: Optional[str] = None  # '1m', '15m', '1h', or None
    estimator_type: str = "exact"  # 'exact', 'wilder_smoothed', 'rs_single_window_proxy'
    interpretation: str = "standard"  # 'standard', 'research_feature_only'
    session_definition_version: Optional[str] = None
    version: str = "2.0.0"


@dataclass(frozen=True)
class FeatureEngineInput:
    """Input payload contract for FeatureEngine computation."""

    candles_primary: Tuple[CanonicalCandle, ...]  # 5m bars, strictly sorted ASC
    context_candles: Dict[str, Tuple[CanonicalCandle, ...]]  # {"1m": ..., "15m": ..., "1h": ...}
    venue: str
    instrument: str
    primary_timeframe: str = "5m"
    input_dataset_version: str = "v1.1.0"
    session_definition_version: str = "1.0.0"


class FeatureDatasetManifest(BaseModel):
    """Manifest describing a versioned feature dataset and its complete provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "2.0.0"
    feature_set_version: str = "v2.0.0"
    dataset_id: str
    created_at_utc: str
    input_dataset: Dict[str, Any]
    engine: Dict[str, Any]
    session_definition_version: str
    feature_clock: Dict[str, Any]
    coverage: Dict[str, Any]
    feature_catalog: Dict[str, Any]
    determinism: Dict[str, Any]
    storage: Dict[str, Any]
