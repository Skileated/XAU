"""Configuration provenance recording for reproducible quantitative research."""

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict


def mask_sensitive_data(data: Any) -> Any:
    """Recursively mask keys containing sensitive substrings."""
    sensitive_keywords = {"key", "secret", "token", "password", "credential", "auth"}

    if isinstance(data, dict):
        masked = {}
        for k, v in data.items():
            if any(keyword in str(k).lower() for keyword in sensitive_keywords):
                masked[k] = "***MASKED***"
            else:
                masked[k] = mask_sensitive_data(v)
        return masked
    elif isinstance(data, list):
        return [mask_sensitive_data(item) for item in data]
    return data


@dataclass(frozen=True)
class ConfigProvenance:
    """Immutable audit record capturing configuration provenance."""

    environment: str
    config_file: str
    loaded_at: str
    config_hash: str
    resolved_config: Dict[str, Any]

    @classmethod
    def create(
        cls, environment: str, config_file: str, raw_config: Dict[str, Any]
    ) -> "ConfigProvenance":
        """Factory method computing hash and masked config snapshot."""
        now_utc = datetime.now(timezone.utc).isoformat()
        # Canonical JSON string for deterministic SHA-256 calculation
        canonical_json = json.dumps(raw_config, sort_keys=True, default=str)
        config_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
        masked_config = mask_sensitive_data(raw_config)

        return cls(
            environment=environment,
            config_file=config_file,
            loaded_at=now_utc,
            config_hash=config_hash,
            resolved_config=masked_config,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize provenance metadata to dictionary."""
        return asdict(self)

    def __repr__(self) -> str:
        return (
            f"ConfigProvenance(environment='{self.environment}', "
            f"config_file='{self.config_file}', "
            f"config_hash='{self.config_hash[:8]}...', "
            f"loaded_at='{self.loaded_at}')"
        )
