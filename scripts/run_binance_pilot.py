"""Runner script for Phase 1A Binance BTCUSDT Spot Pilot.

Executes:
1. Public endpoint verification (/api/v3/ping, /api/v3/time)
2. Historical data acquisition (120 1m candles) -> raw preservation
3. Canonical normalization
4. Data validation and gap detection
5. Parquet export and DuckDB analytical inspection
6. Cryptographic provenance manifest generation
7. Public WebSocket connectivity and clock-compensated latency probe
"""

import json

from rich.console import Console

from xau_quant.data.binance import BinanceSpotProvider
from xau_quant.data.manifest import ProvenanceManifest
from xau_quant.data.normalizer import BinanceKlineNormalizer
from xau_quant.data.storage import ParquetCandleStorage
from xau_quant.data.validator import MarketDataValidator

console = Console()


def run_pilot() -> None:
    console.print("[bold gold1]=== XAU Quantitative Platform: Phase 1A Pilot ===[/bold gold1]\n")
    provider = BinanceSpotProvider()

    # Step 1: Endpoint Ping & Clock Check
    console.print("[bold cyan]1. Testing Binance Public Endpoints...[/bold cyan]")
    ping_ok = provider.ping()
    server_time_ms = provider.get_server_time()
    console.print(f"  REST Ping Status: {'[green]PASS[/green]' if ping_ok else '[red]FAIL[/red]'}")
    console.print(f"  Binance Server Time (ms): {server_time_ms}\n")
    if not ping_ok:
        raise RuntimeError("Binance public ping failed!")

    # Step 2: Acquire Historical Sample (120 1m candles = 2 hours)
    symbol = "BTCUSDT"
    timeframe = "1m"
    limit = 120
    console.print(
        f"[bold cyan]2. Acquiring Genuine Historical Sample "
        f"({limit} {timeframe} candles)...[/bold cyan]"
    )
    raw_path, raw_bytes, meta = provider.fetch_historical_raw(
        symbol=symbol,
        interval=timeframe,
        limit=limit,
    )
    console.print(f"  Raw response saved to: [green]{raw_path}[/green]")
    console.print(f"  Raw SHA-256: {meta['sha256']}")
    console.print(
        f"  HTTP status: {meta['http_status']}, "
        f"Request elapsed: {meta['request_elapsed_seconds']}s\n"
    )

    # Step 3: Canonical Normalization
    console.print("[bold cyan]3. Normalizing to CanonicalCandle models...[/bold cyan]")
    candles = BinanceKlineNormalizer.normalize_payload(
        raw_bytes, instrument=symbol, timeframe=timeframe
    )
    console.print(f"  Normalized count: {len(candles)} records")
    console.print(
        f"  Earliest candle: {candles[0].timestamp_utc.isoformat()} (Open: {candles[0].open})"
    )
    console.print(
        f"  Latest candle:   {candles[-1].timestamp_utc.isoformat()} (Close: {candles[-1].close})\n"
    )

    # Step 4: Validation
    console.print("[bold cyan]4. Running Comprehensive Validation Battery...[/bold cyan]")
    validator = MarketDataValidator(expected_timeframe=timeframe)
    report = validator.validate(candles)
    status_str = (
        "[bold green]PASS[/bold green]" if report.is_valid else "[bold red]FAIL[/bold red]"
    )
    console.print(f"  Validation Status: {status_str}")
    console.print(f"  Valid records: {report.valid_records_count}/{report.total_records}")
    console.print(f"  Gaps detected: {len(report.gaps)}")
    console.print(
        f"  Duplicates: {report.duplicate_count}, "
        f"Conflicting duplicates: {report.conflicting_duplicate_count}"
    )
    console.print(f"  Total issues: {len(report.issues)}\n")

    # Step 5: Parquet Storage & DuckDB Verification
    console.print("[bold cyan]5. Saving to Parquet & Inspecting via DuckDB...[/bold cyan]")
    parquet_path, row_count, p_hash = ParquetCandleStorage.save_candles_to_parquet(
        candles, symbol=symbol, timeframe=timeframe
    )
    console.print(f"  Parquet path: [green]{parquet_path}[/green]")
    console.print(f"  Parquet SHA-256: {p_hash}")

    duckdb_summary = ParquetCandleStorage.inspect_parquet(parquet_path)
    console.print("  DuckDB Verification Metrics:")
    for k, v in duckdb_summary.items():
        console.print(f"    {k}: {v}")
    console.print()

    # Step 6: Provenance Manifest
    console.print("[bold cyan]6. Generating Authoritative Provenance Manifest...[/bold cyan]")
    first_str = candles[0].timestamp_utc.strftime("%Y%m%d%H%M")
    last_str = candles[-1].timestamp_utc.strftime("%Y%m%d%H%M")
    dataset_id = f"binance_spot_{symbol.lower()}_{timeframe}_{first_str}_{last_str}"
    manifest = ProvenanceManifest.build(
        dataset_id=dataset_id,
        venue="binance",
        instrument=symbol,
        market_type="spot",
        timeframe=timeframe,
        source_endpoint=meta["endpoint"],
        raw_file_path=raw_path,
        normalized_file_path=parquet_path,
        raw_row_count=len(candles),
        normalized_row_count=row_count,
        validation_report=report,
        requested_start=None,
        requested_end=None,
        actual_start=candles[0].timestamp_utc.isoformat(),
        actual_end=candles[-1].timestamp_utc.isoformat(),
    )
    auth_path, auth_hash = manifest.save_authoritative()
    console.print(f"  Authoritative Manifest saved to: [green]{auth_path}[/green]")
    console.print(f"  Manifest SHA-256: {auth_hash}")

    # Research artifact copy
    artifact_copy_path, copy_hash = ProvenanceManifest.create_artifact_copy(auth_path)
    console.print(f"  Research Artifact copy saved to: [green]{artifact_copy_path}[/green]")
    console.print(f"  Verified Identical Copy SHA-256: {copy_hash}\n")

    # Step 7: WebSocket Probe
    console.print("[bold cyan]7. Executing Live Public WebSocket Stream Probe (5s)...[/bold cyan]")
    ws_result = provider.test_websocket(symbol=symbol, duration_seconds=5.0)
    console.print("  WebSocket Probe Findings:")
    console.print(f"    Stream: {ws_result['stream_used']}")
    console.print(f"    Connection duration: {ws_result['connect_duration_seconds']}s")
    console.print(f"    Measured clock skew (local - server): {ws_result['clock_skew_ms']}ms")
    console.print(f"    Messages received: {ws_result['messages_received_count']}")
    console.print(f"    Average latency (clock-compensated): {ws_result['average_latency_ms']}ms")
    console.print(f"    Clean shutdown: {ws_result['clean_shutdown']}")
    console.print(f"    Sample event: {json.dumps(ws_result['sample_message'])[:120]}...\n")

    console.print(
        "[bold green]=== Phase 1A Pilot Execution Completed Successfully ===[/bold green]"
    )


if __name__ == "__main__":
    run_pilot()
