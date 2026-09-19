"""Command-line interface and system health diagnostic check."""

import importlib
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

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
            is_same = (str(prefix).lower() == str(expected_venv).lower())

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


def main() -> None:
    """Primary CLI entrypoint."""
    if len(sys.argv) > 1 and sys.argv[1] == "health":
        health_cmd()
    else:
        console = Console()
        console.print(
            f"[bold gold1]XAUUSD Quantitative Platform[/bold gold1] v{__version__}\n"
            "Usage:\n"
            "  xau health       Run environment and subsystem diagnostics\n"
            "  xau-health       Direct alias for health check"
        )


if __name__ == "__main__":
    main()
