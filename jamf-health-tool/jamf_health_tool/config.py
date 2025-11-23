"""
Configuration loading and merge utilities.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


class ConfigError(Exception):
    """Raised when configuration cannot be loaded or is invalid."""


@dataclass
class Config:
    target: Optional[str] = None
    limiting_group_id: Optional[int] = None
    default_profile_ids: Optional[list[int]] = None
    config_path: Optional[Path] = None
    tenant_url: Optional[str] = None
    cache_enabled: bool = True  # Enable caching by default
    cache_ttl: int = 3600  # Default TTL: 1 hour
    cache_dir: Optional[Path] = None  # Use default cache dir if None
    concurrency_enabled: bool = True  # Enable concurrent API calls
    max_workers: int = 10  # Maximum concurrent threads
    rate_limit: float = 0  # Requests per second (0 = no limit)


def load_config(cli_target: Optional[str] = None, config_file: Optional[str] = None) -> Config:
    """
    Load configuration from CLI, environment, and optional YAML file.

    Precedence: CLI > environment > config file > defaults.
    """
    env_target = os.environ.get("JAMF_HEALTH_TOOL_TARGET")
    env_config = os.environ.get("JAMF_HEALTH_TOOL_CONFIG")
    config_path = Path(config_file or env_config or Path.home() / ".jamf_health_tool.yml").expanduser()

    file_data: Dict[str, Any] = {}
    if config_path.exists():
        try:
            with config_path.open("r", encoding="utf-8") as handle:
                loaded = yaml.safe_load(handle) or {}
                if not isinstance(loaded, dict):
                    raise ConfigError("Configuration file must contain a mapping.")
                file_data = loaded
        except OSError as exc:
            raise ConfigError(f"Failed to read config file {config_path}") from exc
        except yaml.YAMLError as exc:
            raise ConfigError(f"Invalid YAML in config file {config_path}") from exc

    target = cli_target or env_target or file_data.get("default_target")
    limiting_group_id = file_data.get("default_limiting_group_id")
    default_profile_ids = file_data.get("default_profile_ids")
    tenant_url = file_data.get("tenant_url")

    # Cache configuration
    cache_config = file_data.get("cache", {})
    cache_enabled = cache_config.get("enabled", True) if isinstance(cache_config, dict) else True
    cache_ttl = cache_config.get("ttl", 3600) if isinstance(cache_config, dict) else 3600
    cache_dir_str = cache_config.get("directory") if isinstance(cache_config, dict) else None
    cache_dir = Path(cache_dir_str).expanduser() if cache_dir_str else None

    # Concurrency configuration
    concurrency_config = file_data.get("concurrency", {})
    concurrency_enabled = concurrency_config.get("enabled", True) if isinstance(concurrency_config, dict) else True
    max_workers = concurrency_config.get("max_workers", 10) if isinstance(concurrency_config, dict) else 10
    rate_limit = concurrency_config.get("rate_limit", 0) if isinstance(concurrency_config, dict) else 0

    return Config(
        target=target,
        limiting_group_id=limiting_group_id,
        default_profile_ids=default_profile_ids,
        config_path=config_path if config_path.exists() else None,
        tenant_url=tenant_url,
        cache_enabled=cache_enabled,
        cache_ttl=cache_ttl,
        cache_dir=cache_dir,
        concurrency_enabled=concurrency_enabled,
        max_workers=max_workers,
        rate_limit=rate_limit,
    )
