"""Market data validation suite enforcing strict integrity, ordering, and consistency."""

from dataclasses import dataclass, field
from datetime import timedelta, timezone
from typing import Dict, List, Optional

from xau_quant.data.models import CanonicalCandle


@dataclass
class ValidationIssue:
    """Represents a specific validation anomaly or error detected in a candle series."""

    issue_type: str
    message: str
    record_index: Optional[int] = None
    timestamp_utc: Optional[str] = None
    details: Dict[str, str] = field(default_factory=dict)


@dataclass
class GapRecord:
    """Explicitly records an unobserved time interval gap in market records."""

    start_timestamp_utc: str
    end_timestamp_utc: str
    expected_step_seconds: int
    missing_intervals_count: int


@dataclass
class ValidationReport:
    """Comprehensive diagnostic results of market data validation."""

    is_valid: bool
    total_records: int
    valid_records_count: int
    invalid_records_count: int
    issues: List[ValidationIssue] = field(default_factory=list)
    gaps: List[GapRecord] = field(default_factory=list)
    duplicate_count: int = 0
    conflicting_duplicate_count: int = 0

    def summary_dict(self) -> Dict[str, object]:
        """Convert report to summary statistics dictionary."""
        return {
            "is_valid": self.is_valid,
            "total_records": self.total_records,
            "valid_records_count": self.valid_records_count,
            "invalid_records_count": self.invalid_records_count,
            "duplicate_count": self.duplicate_count,
            "conflicting_duplicate_count": self.conflicting_duplicate_count,
            "gaps_count": len(self.gaps),
            "total_issues_count": len(self.issues),
        }


class MarketDataValidator:
    """Validates sequence of CanonicalCandle objects according to quantitative standards."""

    TIMEFRAME_SECONDS_MAP = {
        "1m": 60,
        "3m": 180,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "2h": 7200,
        "4h": 14400,
        "1d": 86400,
    }

    def __init__(self, expected_timeframe: str = "1m") -> None:
        self.expected_timeframe = expected_timeframe
        self.expected_step_seconds = self.TIMEFRAME_SECONDS_MAP.get(expected_timeframe, 60)

    def validate(self, candles: List[CanonicalCandle]) -> ValidationReport:
        """Run full battery of validation checks against the candle sequence."""
        issues: List[ValidationIssue] = []
        gaps: List[GapRecord] = []
        seen_timestamps: Dict[str, CanonicalCandle] = {}
        duplicates_count = 0
        conflicting_duplicates_count = 0
        invalid_indices: set[int] = set()

        if not candles:
            return ValidationReport(
                is_valid=True,
                total_records=0,
                valid_records_count=0,
                invalid_records_count=0,
                issues=[],
                gaps=[],
            )

        prev_candle: Optional[CanonicalCandle] = None

        for idx, candle in enumerate(candles):
            is_record_valid = True

            # 1. UTC Timezone enforcement
            if candle.timestamp_utc.tzinfo is None or candle.timestamp_utc.tzinfo != timezone.utc:
                issues.append(
                    ValidationIssue(
                        issue_type="NON_UTC_TIMEZONE",
                        message=f"Candle at index {idx} does not have UTC timezone.",
                        record_index=idx,
                        timestamp_utc=str(candle.timestamp_utc),
                    )
                )
                is_record_valid = False

            # 2. Zero / Negative prices
            if candle.open <= 0 or candle.high <= 0 or candle.low <= 0 or candle.close <= 0:
                issues.append(
                    ValidationIssue(
                        issue_type="NON_POSITIVE_PRICE",
                        message=f"Candle at index {idx} contains zero or negative price: "
                        f"O={candle.open}, H={candle.high}, L={candle.low}, C={candle.close}",
                        record_index=idx,
                        timestamp_utc=candle.timestamp_utc.isoformat(),
                    )
                )
                is_record_valid = False

            # 3. OHLC Consistency
            if candle.high < candle.low:
                issues.append(
                    ValidationIssue(
                        issue_type="OHLC_HIGH_LESS_THAN_LOW",
                        message=(
                            f"High ({candle.high}) lower than low ({candle.low}) "
                            f"at index {idx}."
                        ),
                        record_index=idx,
                        timestamp_utc=candle.timestamp_utc.isoformat(),
                    )
                )
                is_record_valid = False

            if candle.open < candle.low or candle.open > candle.high:
                issues.append(
                    ValidationIssue(
                        issue_type="OHLC_OPEN_OUT_OF_RANGE",
                        message=(
                            f"Open ({candle.open}) outside [low={candle.low}, "
                            f"high={candle.high}] at index {idx}."
                        ),
                        record_index=idx,
                        timestamp_utc=candle.timestamp_utc.isoformat(),
                    )
                )
                is_record_valid = False

            if candle.close < candle.low or candle.close > candle.high:
                issues.append(
                    ValidationIssue(
                        issue_type="OHLC_CLOSE_OUT_OF_RANGE",
                        message=(
                            f"Close ({candle.close}) outside [low={candle.low}, "
                            f"high={candle.high}] at index {idx}."
                        ),
                        record_index=idx,
                        timestamp_utc=candle.timestamp_utc.isoformat(),
                    )
                )
                is_record_valid = False

            # 4. Volume and Taker Volume Consistency
            if candle.volume < 0 or candle.quote_volume < 0:
                issues.append(
                    ValidationIssue(
                        issue_type="NEGATIVE_VOLUME",
                        message=f"Volume cannot be negative at index {idx}.",
                        record_index=idx,
                        timestamp_utc=candle.timestamp_utc.isoformat(),
                    )
                )
                is_record_valid = False

            if candle.taker_buy_base_volume > candle.volume + 1e-7:
                issues.append(
                    ValidationIssue(
                        issue_type="TAKER_VOLUME_EXCEEDS_TOTAL",
                        message=(
                            f"Taker buy volume ({candle.taker_buy_base_volume}) "
                            f"exceeds total volume ({candle.volume}) at index {idx}."
                        ),
                        record_index=idx,
                        timestamp_utc=candle.timestamp_utc.isoformat(),
                    )
                )
                is_record_valid = False

            # 5. Trade count check
            if candle.trade_count < 0:
                issues.append(
                    ValidationIssue(
                        issue_type="NEGATIVE_TRADE_COUNT",
                        message=f"Trade count must be non-negative at index {idx}.",
                        record_index=idx,
                        timestamp_utc=candle.timestamp_utc.isoformat(),
                    )
                )
                is_record_valid = False

            # 6. Chronological Ordering and Duplicate Check
            ts_key = candle.timestamp_utc.isoformat()
            if ts_key in seen_timestamps:
                prior = seen_timestamps[ts_key]
                if (
                    prior.open == candle.open
                    and prior.high == candle.high
                    and prior.low == candle.low
                    and prior.close == candle.close
                    and prior.volume == candle.volume
                ):
                    duplicates_count += 1
                    issues.append(
                        ValidationIssue(
                            issue_type="EXACT_DUPLICATE",
                            message=(
                                f"Exact duplicate candle at index {idx} "
                                f"matching earlier record."
                            ),
                            record_index=idx,
                            timestamp_utc=ts_key,
                        )
                    )
                else:
                    conflicting_duplicates_count += 1
                    issues.append(
                        ValidationIssue(
                            issue_type="CONFLICTING_DUPLICATE",
                            message=(
                                f"Conflicting duplicate prices for timestamp "
                                f"{ts_key} at index {idx}."
                            ),
                            record_index=idx,
                            timestamp_utc=ts_key,
                        )
                    )
                is_record_valid = False
            else:
                seen_timestamps[ts_key] = candle

            # 7. Monotonic Ordering & Interval Gap Detection
            if prev_candle is not None:
                delta = (candle.timestamp_utc - prev_candle.timestamp_utc).total_seconds()
                if delta <= 0:
                    issues.append(
                        ValidationIssue(
                            issue_type="TIMESTAMP_OUT_OF_ORDER",
                            message=(
                                f"Timestamp at index {idx} ({candle.timestamp_utc}) "
                                f"is <= previous ({prev_candle.timestamp_utc})."
                            ),
                            record_index=idx,
                            timestamp_utc=ts_key,
                        )
                    )
                    is_record_valid = False
                elif delta > self.expected_step_seconds:
                    missing_steps = int(round(delta / self.expected_step_seconds)) - 1
                    gaps.append(
                        GapRecord(
                            start_timestamp_utc=(
                                prev_candle.timestamp_utc
                                + timedelta(seconds=self.expected_step_seconds)
                            ).isoformat(),
                            end_timestamp_utc=(
                                candle.timestamp_utc - timedelta(seconds=self.expected_step_seconds)
                            ).isoformat(),
                            expected_step_seconds=self.expected_step_seconds,
                            missing_intervals_count=missing_steps,
                        )
                    )
                    issues.append(
                        ValidationIssue(
                            issue_type="DATA_GAP_DETECTED",
                            message=(
                                f"Detected gap of {delta}s ({missing_steps} missing "
                                f"{self.expected_timeframe} intervals) between index "
                                f"{idx - 1} and {idx}."
                            ),
                            record_index=idx,
                            timestamp_utc=ts_key,
                            details={
                                "delta_seconds": str(delta),
                                "missing_steps": str(missing_steps),
                            },
                        )
                    )

            if not is_record_valid:
                invalid_indices.add(idx)

            prev_candle = candle

        total_records = len(candles)
        invalid_count = len(invalid_indices)
        valid_count = total_records - invalid_count

        # A series is considered strictly valid if there are no data corruption issues
        critical_issues = [iss for iss in issues if iss.issue_type != "DATA_GAP_DETECTED"]
        is_overall_valid = len(critical_issues) == 0

        return ValidationReport(
            is_valid=is_overall_valid,
            total_records=total_records,
            valid_records_count=valid_count,
            invalid_records_count=invalid_count,
            issues=issues,
            gaps=gaps,
            duplicate_count=duplicates_count,
            conflicting_duplicate_count=conflicting_duplicates_count,
        )
