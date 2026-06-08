"""
Config Store — persistent configuration saved as JSON alongside the database.

Allows reading and writing config values that persist between sessions.
Values are stored in a JSON file (`regog_config.json` by default) alongside
the database.

Usage:
    from utils.config_store import get_config, set_config, load_config

    # Read a value
    radius = get_config("comp_radius_miles", default=3)

    # Write a value (persists to disk)
    set_config("comp_radius_miles", 5)
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from config import DB_PATH

logger = logging.getLogger(__name__)

# Config file sits next to the database file
CONFIG_FILE = str(Path(DB_PATH).parent / "regog_config.json")

# In-memory cache
_config: dict[str, Any] = {}


def load_config() -> dict[str, Any]:
    """
    Load config from disk into memory.

    Returns:
        The full config dict (empty if file doesn't exist).
    """
    global _config
    config_path = Path(CONFIG_FILE)
    if config_path.exists():
        try:
            with open(config_path) as f:
                _config = json.load(f)
            logger.debug(f"Config loaded from {CONFIG_FILE}: {len(_config)} keys")
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load config from {CONFIG_FILE}: {e}")
            _config = {}
    else:
        _config = {}
    return _config


def save_config() -> None:
    """Save the current config to disk."""
    global _config
    config_path = Path(CONFIG_FILE)
    try:
        # Ensure parent directory exists
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w") as f:
            json.dump(_config, f, indent=2)
        logger.debug(f"Config saved to {CONFIG_FILE}: {len(_config)} keys")
    except OSError as e:
        logger.warning(f"Failed to save config to {CONFIG_FILE}: {e}")


def get_config(key: str, default: Any = None) -> Any:
    """
    Get a config value by key.

    Args:
        key: Config key (e.g. 'comp_radius_miles').
        default: Value to return if key is not set.

    Returns:
        The stored value, or default if not found.
    """
    global _config
    if not _config:
        load_config()
    return _config.get(key, default)


def set_config(key: str, value: Any) -> None:
    """
    Set a config value and persist to disk immediately.

    Args:
        key: Config key (e.g. 'comp_radius_miles').
        value: Any JSON-serializable value.
    """
    global _config
    if not _config:
        load_config()
    _config[key] = value
    save_config()


def delete_config(key: str) -> bool:
    """
    Delete a config key.

    Args:
        key: Config key to delete.

    Returns:
        True if key existed and was deleted, False otherwise.
    """
    global _config
    if not _config:
        load_config()
    if key in _config:
        del _config[key]
        save_config()
        return True
    return False


def list_config() -> dict[str, Any]:
    """
    List all stored config values.

    Returns:
        Dict of all config keys and their values.
    """
    global _config
    if not _config:
        load_config()
    return dict(_config)
