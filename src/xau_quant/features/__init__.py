"""Market Feature Engine package for deterministic multi-timeframe quantitative features."""

from xau_quant.features.engine import FeatureEngine
from xau_quant.features.manifest import build_feature_dataset_manifest
from xau_quant.features.models import (
    ColumnSpec,
    FeatureDatasetManifest,
    FeatureDefinition,
    FeatureEngineInput,
)
from xau_quant.features.registry import FeatureRegistry
from xau_quant.features.storage import FeatureParquetStorage
from xau_quant.features.validators import (
    FeatureInputValidator,
    FeatureOutputValidator,
    FeatureValidationError,
)

__all__ = [
    "FeatureEngine",
    "FeatureRegistry",
    "FeatureParquetStorage",
    "FeatureEngineInput",
    "FeatureDefinition",
    "ColumnSpec",
    "FeatureDatasetManifest",
    "build_feature_dataset_manifest",
    "FeatureValidationError",
    "FeatureInputValidator",
    "FeatureOutputValidator",
]
