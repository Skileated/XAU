"""Market data acquisition, normalization, validation, and storage subsystem."""

from xau_quant.data.binance import BinanceSpotProvider
from xau_quant.data.manifest import ProvenanceManifest
from xau_quant.data.models import CanonicalCandle
from xau_quant.data.normalizer import BinanceKlineNormalizer
from xau_quant.data.provider import DataProvider
from xau_quant.data.storage import ParquetCandleStorage
from xau_quant.data.validator import MarketDataValidator, ValidationReport

__all__ = [
    "CanonicalCandle",
    "DataProvider",
    "BinanceSpotProvider",
    "BinanceKlineNormalizer",
    "MarketDataValidator",
    "ValidationReport",
    "ParquetCandleStorage",
    "ProvenanceManifest",
]
