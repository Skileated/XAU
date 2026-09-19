"""Pydantic v2 schemas for typed, validated platform configurations."""

from typing import Any, Dict, Literal

from pydantic import BaseModel, ConfigDict, Field

EnvironmentType = Literal["development", "research", "paper"]


class LoggingConfig(BaseModel):
    """Logging settings."""

    model_config = ConfigDict(extra="forbid")

    level: str = Field(
        default="INFO", description="Minimum log level: DEBUG, INFO, WARNING, ERROR"
    )
    format: str = Field(default="text", description="Log format style: text or json")
    max_bytes: int = Field(
        default=10 * 1024 * 1024, description="Log rotation max file size in bytes"
    )
    backup_count: int = Field(default=5, description="Number of rotated archives to retain")
    enable_console: bool = Field(default=True, description="Output logs to console")
    enable_file: bool = Field(default=True, description="Output logs to rotating file")


class StorageConfig(BaseModel):
    """Analytical storage configuration."""

    model_config = ConfigDict(extra="forbid")

    engine: str = Field(default="duckdb", description="Storage backend engine")
    database_filename: str = Field(default="xau_analytics.duckdb", description="DuckDB file name")
    memory_limit: str = Field(default="2GB", description="DuckDB memory ceiling")


class DataConfig(BaseModel):
    """Market data parameters (metadata only, no fake data)."""

    model_config = ConfigDict(extra="forbid")

    primary_symbol: str = Field(default="XAUUSD", description="Target market instrument")
    base_currency: str = Field(default="XAU", description="Base asset (Gold)")
    quote_currency: str = Field(default="USD", description="Quote currency")
    timezone: str = Field(default="UTC", description="Standardized timestamp timezone")


class AppConfig(BaseModel):
    """Root configuration schema for XAUUSD Quantitative Platform."""

    model_config = ConfigDict(extra="allow")

    environment: EnvironmentType = Field(description="Operational environment")
    project_name: str = Field(
        default="xau-quant-platform", description="Platform project identifier"
    )
    version: str = Field(default="0.1.0", description="Codebase release version")
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    custom: Dict[str, Any] = Field(
        default_factory=dict, description="Environment-specific extra settings"
    )
