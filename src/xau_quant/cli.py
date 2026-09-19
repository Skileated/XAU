"""Command-line interface and system health diagnostic check."""

import importlib
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from xau_quant import __version__
from xau_quant.common.logging import setup_logger
from xau_quant.common.paths import project_paths
from xau_quant.config.loader import load_config


class SystemHealthChecker:
    """Executes non-destructive diagnostics verifying system integrity."""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()
        self.results: List[Tuple[str, bool, str]] = []

    def check_python_version(self) -> Tuple[bool, str]:
        """Check if Python version satisfies >=3.12, <3.13."""
        version_info = sys.version_info
        actual_str = f"{version_info.major}.{version_info.minor}.{version_info.micro}"
        expected_str = ">=3.12, <3.13"
        is_valid = (version_info.major == 3) and (version_info.minor == 12)
        status_msg = f"Expected: {expected_str} | Actual: Python {actual_str}"
        return is_valid, status_msg

    def check_virtual_env(self) -> Tuple[bool, str]:
        """Check if executing inside the project-local .venv."""
        prefix = Path(sys.prefix).resolve()
        expected_venv = (project_paths.root / ".venv").resolve()
        is_same = False
        try:
            is_same = prefix.samefile(expected_venv)
        except Exception:
            is_same = str(prefix).lower() == str(expected_venv).lower()

        is_venv = is_same or (sys.base_prefix != sys.prefix and ".venv" in str(prefix).lower())
        msg = f"Virtualenv Path: {prefix} (Project Local: {is_same})"
        return is_venv, msg

    def check_directory_structure(self) -> Tuple[bool, str]:
        """Verify existence and writability of all structural repository directories."""
        dirs = project_paths.get_all_structural_dirs()
        missing = [d for d in dirs if not (d.exists() and d.is_dir())]
        if missing:
            rel_missing = [str(d.relative_to(project_paths.root)) for d in missing]
            return False, f"Missing directories: {rel_missing}"

        # Test writability on key writable targets
        writable_targets = [
            project_paths.data_raw,
            project_paths.artifacts_reports,
            project_paths.logs_development,
        ]
        unwritable = [d for d in writable_targets if not project_paths.check_writability(d)]
        if unwritable:
            rel_unwritable = [str(d.relative_to(project_paths.root)) for d in unwritable]
            return False, f"Directories not writable: {rel_unwritable}"

        return True, f"All {len(dirs)} structural directories present and verified writable"

    def check_dependencies(self) -> Tuple[bool, str]:
        """Verify required core and dev packages are importable."""
        required = [
            ("pydantic", "pydantic"),
            ("yaml", "PyYAML"),
            ("dotenv", "python-dotenv"),
            ("rich", "rich"),
            ("duckdb", "duckdb"),
            ("websockets", "websockets"),
            ("pytest", "pytest"),
        ]
        missing = []
        versions = []
        for mod, pkg in required:
            try:
                m = importlib.import_module(mod)
                v = getattr(m, "__version__", "installed")
                versions.append(f"{pkg}={v}")
            except ImportError:
                missing.append(pkg)

        if missing:
            return False, f"Missing packages: {', '.join(missing)}"
        return True, f"Verified: {', '.join(versions)}"

    def check_configurations(self) -> Tuple[bool, str]:
        """Verify that all default environment configurations load and validate."""
        envs = ["development", "research", "paper"]
        loaded_provenances = []
        for env_name in envs:
            try:
                cfg, prov = load_config(env=env_name)
                loaded_provenances.append(f"{env_name}: OK (hash={prov.config_hash[:8]})")
            except Exception as exc:
                return False, f"Failed loading {env_name}.yaml: {exc}"

        return True, " | ".join(loaded_provenances)

    def check_logging(self) -> Tuple[bool, str]:
        """Verify console and rotating file logger initialization."""
        logger = None
        try:
            logger = setup_logger(
                name="xau_health_test",
                env="development",
                log_level="INFO",
                enable_console=False,
                enable_file=True,
            )
            logger.info("Health check logging verification message.")
            log_file = project_paths.logs_development / "xau_quant.log"
            if not log_file.exists():
                return False, f"Log file was not created at {log_file}"
            return True, f"Logging verified: writing to {log_file.relative_to(project_paths.root)}"
        except Exception as exc:
            return False, f"Logging verification failed: {exc}"
        finally:
            if logger is not None:
                for handler in list(logger.handlers):
                    handler.close()
                    logger.removeHandler(handler)

    def check_git_status(self) -> Tuple[bool, str]:
        """Check Git repository presence, branch, HEAD, and working tree state non-destructively."""
        try:
            # Check if git root exists
            root_res = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=str(project_paths.root),
                capture_output=True,
                text=True,
                check=False,
            )
            if root_res.returncode != 0:
                return False, "Not a Git repository"

            # Check branch
            branch_res = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=str(project_paths.root),
                capture_output=True,
                text=True,
                check=False,
            )
            branch = branch_res.stdout.strip() or "(detached/init)"

            # Check HEAD commit
            head_res = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(project_paths.root),
                capture_output=True,
                text=True,
                check=False,
            )
            if head_res.returncode == 0:
                head = head_res.stdout.strip()
            else:
                head = "No commits yet (Clean initial state)"

            # Check working tree dirty/clean
            status_res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(project_paths.root),
                capture_output=True,
                text=True,
                check=False,
            )
            is_dirty = bool(status_res.stdout.strip())
            tree_state = "DIRTY (uncommitted files present)" if is_dirty else "CLEAN"

            return True, f"Branch: {branch} | HEAD: {head} | Working tree: {tree_state}"
        except Exception as exc:
            return False, f"Git diagnostic check failed: {exc}"

    def run_all(self) -> bool:
        """Runs all checks and prints formatted summary table. Returns True if all pass."""
        checks = [
            ("Python Version", self.check_python_version),
            ("Virtual Environment", self.check_virtual_env),
            ("Repository Layout & Permissions", self.check_directory_structure),
            ("Dependencies & DuckDB", self.check_dependencies),
            ("Configuration Subsystem", self.check_configurations),
            ("Structured Logging", self.check_logging),
            ("Git Repository State", self.check_git_status),
        ]

        all_passed = True
        title = f"XAUUSD Platform Health Check (v{__version__})"
        table = Table(title=title, header_style="bold cyan")
        table.add_column("Subsystem Check", style="bold")
        table.add_column("Status", justify="center")
        table.add_column("Diagnostics / Details", style="dim")

        for title, check_func in checks:
            passed, msg = check_func()
            self.results.append((title, passed, msg))
            status_str = "[bold green]PASS[/bold green]" if passed else "[bold red]FAIL[/bold red]"
            table.add_row(title, status_str, msg)
            if not passed:
                all_passed = False

        self.console.print(table)
        overall_panel = Panel(
            "[bold green]ALL HEALTH CHECKS PASSED[/bold green]"
            if all_passed
            else "[bold red]SYSTEM HEALTH CHECK DETECTED FAILURES[/bold red]",
            title="System Assessment",
            border_style="green" if all_passed else "red",
        )
        self.console.print(overall_panel)
        return all_passed


def health_cmd() -> None:
    """CLI entrypoint for xau-health."""
    checker = SystemHealthChecker()
    success = checker.run_all()
    sys.exit(0 if success else 1)


def data_cmd() -> None:
    """CLI handler for market data operations."""
    console = Console()
    args = sys.argv[2:]
    action = args[0] if args else "help"

    if action == "ws-test":
        symbol = "BTCUSDT"
        duration = 5.0
        for i, a in enumerate(args):
            if a in ("-s", "--symbol") and i + 1 < len(args):
                symbol = args[i + 1]
            if a in ("-d", "--duration") and i + 1 < len(args):
                duration = float(args[i + 1])

        console.print(
            f"[bold cyan]Connecting to Binance public WebSocket "
            f"({symbol}@trade) for {duration}s...[/bold cyan]"
        )
        from xau_quant.data.binance import BinanceSpotProvider

        provider = BinanceSpotProvider()
        res = provider.test_websocket(symbol=symbol, duration_seconds=duration)
        console.print("[bold green]WebSocket Test Completed cleanly:[/bold green]")
        console.print(f"  Stream: {res['stream_used']}")
        console.print(f"  Connect duration: {res['connect_duration_seconds']}s")
        console.print(f"  Clock skew (local - server): {res['clock_skew_ms']}ms")
        console.print(f"  Messages received: {res['messages_received_count']}")
        console.print(f"  Average latency: {res['average_latency_ms']}ms")
        console.print(f"  Clean shutdown: {res['clean_shutdown']}")
    elif action == "acquire":
        symbol = "BTCUSDT"
        limit = 120
        timeframe = "1m"
        for i, a in enumerate(args):
            if a in ("-s", "--symbol") and i + 1 < len(args):
                symbol = args[i + 1]
            if a in ("-l", "--limit") and i + 1 < len(args):
                limit = int(args[i + 1])
            if a in ("-t", "--timeframe") and i + 1 < len(args):
                timeframe = args[i + 1]

        console.print(
            f"[bold cyan]Acquiring {limit} {timeframe} candles "
            f"for {symbol} from Binance Spot...[/bold cyan]"
        )
        from xau_quant.data.binance import BinanceSpotProvider
        from xau_quant.data.manifest import ProvenanceManifest
        from xau_quant.data.normalizer import BinanceKlineNormalizer
        from xau_quant.data.storage import ParquetCandleStorage
        from xau_quant.data.validator import MarketDataValidator

        provider = BinanceSpotProvider()
        raw_path, raw_bytes, meta = provider.fetch_historical_raw(
            symbol=symbol, interval=timeframe, limit=limit
        )
        console.print(
            f"[green]Raw data saved:[/green] {raw_path} (SHA-256: {meta['sha256'][:16]}...)"
        )

        candles = BinanceKlineNormalizer.normalize_payload(
            raw_bytes, instrument=symbol, timeframe=timeframe
        )
        console.print(f"[green]Normalized:[/green] {len(candles)} CanonicalCandle instances")

        validator = MarketDataValidator(expected_timeframe=timeframe)
        report = validator.validate(candles)
        status_str = (
            "[bold green]PASS[/bold green]" if report.is_valid else "[bold red]FAIL[/bold red]"
        )
        console.print(
            f"Validation: {status_str} ("
            f"{report.valid_records_count}/{report.total_records} valid, "
            f"{len(report.gaps)} gaps, {len(report.issues)} issues)"
        )

        parquet_path, row_count, parquet_hash = ParquetCandleStorage.save_candles_to_parquet(
            candles, symbol=symbol, timeframe=timeframe
        )
        console.print(
            f"[green]Stored Parquet:[/green] {parquet_path} (SHA-256: {parquet_hash[:16]}...)"
        )

        import uuid

        dataset_id = f"binance_spot_{symbol.lower()}_{timeframe}_{uuid.uuid4().hex[:8]}"
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
        console.print(
            f"[bold green]Authoritative Manifest saved:[/bold green] "
            f"{auth_path} (SHA-256: {auth_hash[:16]}...)"
        )
    elif action == "backfill":
        from datetime import datetime, timezone

        from xau_quant.data.backfill import BackfillEngine
        from xau_quant.data.storage import ParquetCandleStorage

        symbol = "BTCUSDT"
        timeframe = "1m"
        start_str: Optional[str] = None
        end_str: Optional[str] = None
        chunk_limit = 1000
        resume = True

        for i, a in enumerate(args):
            if a in ("-s", "--symbol") and i + 1 < len(args):
                symbol = args[i + 1]
            if a in ("--start",) and i + 1 < len(args):
                start_str = args[i + 1]
            if a in ("--end",) and i + 1 < len(args):
                end_str = args[i + 1]
            if a in ("-l", "--chunk-limit") and i + 1 < len(args):
                chunk_limit = int(args[i + 1])
            if a == "--no-resume":
                resume = False

        if not start_str or not end_str:
            console.print(
                "[bold red]Error: --start and --end (ISO format) are required.[/bold red]"
            )
            sys.exit(1)

        start_dt = datetime.fromisoformat(start_str)
        end_dt = datetime.fromisoformat(end_str)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)

        console.print(
            f"[bold cyan]Starting historical backfill for {symbol} "
            f"({start_dt.isoformat()} to {end_dt.isoformat()})...[/bold cyan]"
        )

        engine = BackfillEngine()
        bf_res = engine.run(
            symbol=symbol,
            timeframe=timeframe,
            start_utc=start_dt,
            end_utc=end_dt,
            chunk_limit=chunk_limit,
            resume=resume,
        )

        val_status_str = (
            "[green]PASS[/green]" if bf_res.validation_report.is_valid else "[red]FAIL[/red]"
        )
        console.print(
            f"[bold green]Backfill completed in {bf_res.duration_seconds:.2f}s![/bold green]"
        )
        console.print(
            f"  Chunks completed: "
            f"{bf_res.checkpoint.chunks_completed}/{bf_res.checkpoint.total_chunks_planned}"
        )
        console.print(f"  Total 1m candles: {bf_res.total_records}")
        console.print(f"  Validation status: {val_status_str}")
        console.print(f"  Gaps detected: {len(bf_res.validation_report.gaps)}")

        # Save Parquet
        p_path, count, p_hash = ParquetCandleStorage.save_candles_to_parquet(
            bf_res.candles, symbol=symbol, timeframe=timeframe
        )
        console.print(f"  Parquet stored at: [green]{p_path}[/green] (SHA-256: {p_hash[:16]}...)")
    elif action == "resample":
        from pathlib import Path

        from xau_quant.data.resampler import MultiTimeframeResampler
        from xau_quant.data.storage import ParquetCandleStorage

        symbol = "BTCUSDT"
        parquet_str: Optional[str] = None
        tf_str = "5m,15m,1h,4h,1d"

        for i, a in enumerate(args):
            if a in ("-s", "--symbol") and i + 1 < len(args):
                symbol = args[i + 1]
            if a in ("-p", "--parquet") and i + 1 < len(args):
                parquet_str = args[i + 1]
            if a in ("-t", "--timeframes") and i + 1 < len(args):
                tf_str = args[i + 1]

        if not parquet_str:
            console.print("[bold red]Error: --parquet path to 1m dataset required.[/bold red]")
            sys.exit(1)

        p_path = Path(parquet_str)
        if not p_path.exists():
            console.print(f"[bold red]File not found: {p_path}[/bold red]")
            sys.exit(1)

        candles_1m = ParquetCandleStorage.load_candles_from_parquet(p_path)
        target_tfs = [t.strip() for t in tf_str.split(",")]
        console.print(f"Loaded {len(candles_1m)} 1m candles. Resampling to {target_tfs}...")

        results = MultiTimeframeResampler.resample_all(candles_1m, timeframes=target_tfs)
        for tf, candles in results.items():
            out_path, count, sha = ParquetCandleStorage.save_candles_to_parquet(
                candles, symbol=symbol, timeframe=tf
            )
            complete = sum(1 for c in candles if c.is_complete)
            console.print(
                f"  [{tf}] Generated {count} candles ({complete}/{count} complete) -> "
                f"{out_path.name} (SHA-256: {sha[:12]}...)"
            )
    elif action == "expand":
        from xau_quant.data.expansion import HistoricalExpansionEngine

        symbol = "BTCUSDT"
        timeframe = "1m"
        start_year = 2023
        start_month = 9
        end_year = 2026
        end_month = 9
        resume = True

        for i, a in enumerate(args):
            if a in ("-s", "--symbol") and i + 1 < len(args):
                symbol = args[i + 1]
            if a in ("--start-year",) and i + 1 < len(args):
                start_year = int(args[i + 1])
            if a in ("--start-month",) and i + 1 < len(args):
                start_month = int(args[i + 1])
            if a in ("--end-year",) and i + 1 < len(args):
                end_year = int(args[i + 1])
            if a in ("--end-month",) and i + 1 < len(args):
                end_month = int(args[i + 1])
            if a == "--no-resume":
                resume = False

        console.print(
            f"[bold cyan]Launching historical expansion for {symbol} "
            f"({start_year}-{start_month:02d} to {end_year}-{end_month:02d})...[/bold cyan]"
        )
        exp_engine = HistoricalExpansionEngine()
        exp_result = exp_engine.run(
            symbol=symbol,
            timeframe=timeframe,
            start_year=start_year,
            start_month=start_month,
            end_year=end_year,
            end_month=end_month,
            resume=resume,
        )
        console.print(
            f"[bold green]Historical expansion complete! "
            f"Acquired {exp_result.total_1m_rows:,} 1m rows across\n"
            f"{exp_result.total_partitions} partitions in "
            f"{exp_result.duration_seconds:.2f}s.[/bold green]"
        )
    elif action == "gaps":
        from xau_quant.data.gap_registry import GapRegistry

        registry = GapRegistry()
        gaps = registry.get_all_gaps()
        if not gaps:
            console.print(
                "[bold green]Zero market data gaps registered in Gap Registry.[/bold green]"
            )
        else:
            table = Table(title="Market Data Gap Registry", header_style="bold cyan")
            table.add_column("Gap ID", style="bold")
            table.add_column("Instrument")
            table.add_column("Start UTC")
            table.add_column("End UTC")
            table.add_column("Missing", justify="right")
            table.add_column("Category", style="yellow")
            table.add_column("Evidence")
            for g in gaps:
                table.add_row(
                    g.gap_id,
                    g.instrument,
                    g.actual_missing_start_utc.isoformat(),
                    g.actual_missing_end_utc.isoformat(),
                    str(g.missing_candles_count),
                    g.category.value,
                    g.evidence[:40] + "..." if len(g.evidence) > 40 else g.evidence,
                )
            console.print(table)
    else:
        console.print(
            "Data commands:\n"
            "  xau data acquire --symbol BTCUSDT --limit 120 --timeframe 1m\n"
            "  xau data backfill --symbol BTCUSDT --start <start_iso> --end <end_iso>\n"
            "  xau data expand --symbol BTCUSDT --start-year 2023 --end-year 2026\n"
            "  xau data gaps\n"
            "  xau data resample --symbol BTCUSDT --parquet <path> --timeframes 5m,15m,1h,4h,1d\n"
            "  xau data ws-test --symbol BTCUSDT --duration 5"
        )


def main() -> None:
    """Primary CLI entrypoint."""
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "health":
            health_cmd()
        elif cmd == "data":
            data_cmd()
        else:
            Console().print(f"[red]Unknown command: {cmd}[/red]")
            sys.exit(1)
    else:
        console = Console()
        console.print(
            f"[bold gold1]XAUUSD Quantitative Platform[/bold gold1] v{__version__}\n"
            "Usage:\n"
            "  xau health       Run environment and subsystem diagnostics\n"
            "  xau data ...     Market data operations (acquire, ws-test)\n"
            "  xau-health       Direct alias for health check"
        )


if __name__ == "__main__":
    main()
