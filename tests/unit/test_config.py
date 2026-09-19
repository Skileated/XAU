"""Unit tests for configuration loader, substitution, and provenance."""

import os
from pathlib import Path

import pytest

from xau_quant.common.exceptions import ConfigurationError
from xau_quant.config.loader import load_config
from xau_quant.config.model import AppConfig
from xau_quant.config.provenance import ConfigProvenance, mask_sensitive_data


def test_load_default_configs() -> None:
    """Verify loading of development, research, and paper configs."""
    for env in ("development", "research", "paper"):
        cfg, prov = load_config(env=env)
        assert isinstance(cfg, AppConfig)
        assert isinstance(prov, ConfigProvenance)
        assert cfg.environment == env
        assert prov.environment == env
        assert prov.config_hash is not None
        assert len(prov.config_hash) == 64  # SHA-256


def test_env_var_substitution(fixtures_dir: Path, clean_env: None) -> None:
    """Verify explicit ${VAR} and ${VAR:-default} substitution."""
    os.environ["TEST_LOG_LEVEL"] = "WARNING"
    os.environ["TEST_SECRET_KEY"] = "my_custom_secret_key"
    os.environ["TEST_INT_VAL"] = "99"

    fixture_path = fixtures_dir / "test_config.yaml"
    cfg, prov = load_config(env="development", config_path=fixture_path)

    assert cfg.logging.level == "WARNING"
    assert cfg.custom["int_value"] == 99

    # Verify secret is masked in provenance snapshot
    assert prov.resolved_config["custom"]["secret_api_key"] == "***MASKED***"


def test_invalid_environment() -> None:
    """Verify invalid environment raises ConfigurationError."""
    with pytest.raises(ConfigurationError, match="Invalid environment"):
        load_config(env="invalid_env_name")


def test_missing_config_file() -> None:
    """Verify missing config file raises ConfigurationError."""
    fake_path = Path("configs/non_existent.yaml")
    with pytest.raises(ConfigurationError, match="Configuration file not found"):
        load_config(env="development", config_path=fake_path)


def test_sensitive_masking_nested() -> None:
    """Verify recursive masking helper on nested dicts and lists."""
    sample = {
        "api_key": "secret123",
        "nested": {
            "token": "abc",
            "safe": "visible",
        },
        "list_items": [
            {"password": "xyz", "name": "test"},
        ],
    }
    masked = mask_sensitive_data(sample)
    assert masked["api_key"] == "***MASKED***"
    assert masked["nested"]["token"] == "***MASKED***"
    assert masked["nested"]["safe"] == "visible"
    assert masked["list_items"][0]["password"] == "***MASKED***"
    assert masked["list_items"][0]["name"] == "test"
