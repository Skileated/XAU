"""Deterministic project path resolution and directory management."""

from pathlib import Path
from typing import Dict, List

from xau_quant.common.exceptions import PathResolutionError


class ProjectPaths:
    """Manages deterministic absolute paths anchored at the repository root."""

    def __init__(self, root_override: Path | None = None) -> None:
        if root_override is not None:
            self._root = root_override.resolve()
        else:
            # Anchored 4 levels up: src/xau_quant/common/paths.py -> repository root
            self._root = Path(__file__).resolve().parents[3]

        if not self._root.exists() or not self._root.is_dir():
            raise PathResolutionError(f"Resolved project root does not exist: {self._root}")

    @property
    def root(self) -> Path:
        """Root directory of the repository."""
        return self._root

    @property
    def configs(self) -> Path:
        return self._root / "configs"

    @property
    def src(self) -> Path:
        return self._root / "src"

    @property
    def tests(self) -> Path:
        return self._root / "tests"

    @property
    def research(self) -> Path:
        return self._root / "research"

    @property
    def scripts(self) -> Path:
        return self._root / "scripts"

    # Data directories
    @property
    def data(self) -> Path:
        return self._root / "data"

    @property
    def data_raw(self) -> Path:
        return self.data / "raw"

    @property
    def data_interim(self) -> Path:
        return self.data / "interim"

    @property
    def data_processed(self) -> Path:
        return self.data / "processed"

    @property
    def data_features(self) -> Path:
        return self.data / "features"

    @property
    def data_metadata(self) -> Path:
        return self.data / "metadata"

    # Artifacts directories
    @property
    def artifacts(self) -> Path:
        return self._root / "artifacts"

    @property
    def artifacts_datasets(self) -> Path:
        return self.artifacts / "datasets"

    @property
    def artifacts_backtests(self) -> Path:
        return self.artifacts / "backtests"

    @property
    def artifacts_validation(self) -> Path:
        return self.artifacts / "validation"

    @property
    def artifacts_models(self) -> Path:
        return self.artifacts / "models"

    @property
    def artifacts_reports(self) -> Path:
        return self.artifacts / "reports"

    # Logs directories
    @property
    def logs(self) -> Path:
        return self._root / "logs"

    @property
    def logs_development(self) -> Path:
        return self.logs / "development"

    @property
    def logs_research(self) -> Path:
        return self.logs / "research"

    @property
    def logs_paper(self) -> Path:
        return self.logs / "paper"

    # Apps directory
    @property
    def apps(self) -> Path:
        return self._root / "apps"

    @property
    def apps_dev_ui(self) -> Path:
        return self.apps / "dev_ui"

    def get_all_structural_dirs(self) -> List[Path]:
        """Returns all mandated repository structural directories."""
        return [
            self.configs,
            self.src,
            self.tests,
            self.research,
            self._root / "research" / "experiments",
            self._root / "research" / "notebooks",
            self._root / "research" / "reports",
            self.scripts,
            self.data,
            self.data_raw,
            self.data_interim,
            self.data_processed,
            self.data_features,
            self.data_metadata,
            self.artifacts,
            self.artifacts_datasets,
            self.artifacts_backtests,
            self.artifacts_validation,
            self.artifacts_models,
            self.artifacts_reports,
            self.logs,
            self.logs_development,
            self.logs_research,
            self.logs_paper,
            self.apps,
            self.apps_dev_ui,
        ]

    def verify_structure(self) -> Dict[str, bool]:
        """Check existence of all structural directories without modifying repository."""
        return {
            str(d.relative_to(self._root)): d.exists() and d.is_dir()
            for d in self.get_all_structural_dirs()
        }

    def check_writability(self, directory: Path) -> bool:
        """Check if directory is writable using a non-destructive OS check."""
        try:
            test_file = directory / ".write_test.tmp"
            test_file.touch()
            test_file.unlink()
            return True
        except Exception:
            return False


# Global default instance
project_paths = ProjectPaths()
