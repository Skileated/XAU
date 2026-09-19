"""Configuration loader with environment variable substitution and provenance."""

import os
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml
from dotenv import load_dotenv
from pydantic import ValidationError

from xau_quant.common.exceptions import ConfigurationError
from xau_quant.common.paths import project_paths
from xau_quant.config.model import AppConfig
from xau_quant.config.provenance import ConfigProvenance

# Pattern matching ${VAR_NAME} or ${VAR_NAME:-default_value}
ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z0-9_]+)(?::-([^}]*))?\}")


def _substitute_env_vars(data: Any) -> Any:
    """Recursively replaces ${VAR} and ${VAR:-default} patterns using os.environ."""
    if isinstance(data, str):
        def replacer(match: re.Match) -> str:
            var_name = match.group(1)
            default_val = match.group(2) if match.group(2) is not None else ""
            return os.environ.get(var_name, default_val)

        substituted = ENV_VAR_PATTERN.sub(replacer, data)
        # Type inference for numeric and boolean string substitutions
        if substituted.lower() == "true":
            return True
        if substituted.lower() == "false":
            return False
        if substituted.isdigit():
            return int(substituted)
        return substituted

    elif isinstance(data, dict):
        return {k: _substitute_env_vars(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_substitute_env_vars(item) for item in data]
    return data


def load_config(
    env: Optional[str] = None,
    config_path: Optional[Path] = None,
    dotenv_path: Optional[Path] = None,
) -> Tuple[AppConfig, ConfigProvenance]:
    """Loads, substitutes, validates and attaches provenance to platform configuration.

    Flow:
        1. Determine target environment (argument -> os.environ['APP_ENV'] -> 'development').
        2. Locate YAML configuration file (configs/<env>.yaml or custom path).
        3. Load .env file if present in workspace root.
        4. Parse raw YAML file.
        5. Substitute environment variables (${VAR} / ${VAR:-default}).
        6. Validate against Pydantic AppConfig schema.
        7. Generate ConfigProvenance record (with sensitive values masked).

    Returns:
        Tuple of (AppConfig, ConfigProvenance).

    Raises:
        ConfigurationError: On file missing, YAML syntax error, or Pydantic validation failure.
    """
    # 1. Environment determination
    target_env = (env or os.environ.get("APP_ENV", "development")).strip().lower()
    if target_env not in ("development", "research", "paper"):
        msg = (
            f"Invalid environment '{target_env}'. "
            "Must be one of: 'development', 'research', 'paper'."
        )
        raise ConfigurationError(msg)

    # 2. Config file resolution
    if config_path is not None:
        target_config_file = Path(config_path).resolve()
    else:
        target_config_file = (project_paths.configs / f"{target_env}.yaml").resolve()

    if not target_config_file.exists():
        raise ConfigurationError(
            f"Configuration file not found: {target_config_file}. "
            f"Ensure {target_env}.yaml exists in configs directory."
        )

    # 3. .env loading (local overrides, never committed)
    effective_dotenv = dotenv_path or (project_paths.root / ".env")
    if effective_dotenv.exists():
        load_dotenv(dotenv_path=effective_dotenv, override=False)

    # 4. Parse YAML
    try:
        raw_text = target_config_file.read_text(encoding="utf-8")
        raw_dict: Dict[str, Any] = yaml.safe_load(raw_text) or {}
    except yaml.YAMLError as exc:
        raise ConfigurationError(
            f"YAML parsing syntax error in {target_config_file}: {exc}"
        ) from exc
    except Exception as exc:
        raise ConfigurationError(
            f"Failed to read configuration file {target_config_file}: {exc}"
        ) from exc

    # Ensure environment matches the intended environment
    raw_dict.setdefault("environment", target_env)

    # 5. Environment variable substitution
    substituted_dict = _substitute_env_vars(raw_dict)

    # 6. Pydantic validation
    try:
        app_config = AppConfig.model_validate(substituted_dict)
    except ValidationError as exc:
        raise ConfigurationError(
            f"Configuration validation failed for {target_config_file}:\n{exc}"
        ) from exc

    # 7. Provenance generation
    relative_config_path = str(target_config_file)
    try:
        relative_config_path = str(target_config_file.relative_to(project_paths.root))
    except ValueError:
        pass

    provenance = ConfigProvenance.create(
        environment=target_env,
        config_file=relative_config_path,
        raw_config=substituted_dict,
    )

    return app_config, provenance
