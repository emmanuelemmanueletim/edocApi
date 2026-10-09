"""Configuration helpers for eDocAPI."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_SIZE_PATTERN = re.compile(r"^(\d+(?:\.\d+)?)\s*(B|KB|MB|GB)?$", re.IGNORECASE)

_SIZE_MULTIPLIERS = {
    "B": 1,
    "KB": 1024,
    "MB": 1024 ** 2,
    "GB": 1024 ** 3,
}


def parse_size(value: str | int) -> int:
    """Parse a human-readable size string into bytes.

    Accepts integers (already in bytes) or strings such as:
        "10MB", "25 MB", "100kb", "512"
    """
    if isinstance(value, int):
        if value < 0:
            raise ValueError("Size must be non-negative")
        return value

    value = value.strip()
    match = _SIZE_PATTERN.match(value)
    if not match:
        raise ValueError(
            f"Invalid size format: {value!r}. "
            "Expected formats like '10MB', '25MB', '100KB'."
        )

    number = float(match.group(1))
    unit = (match.group(2) or "B").upper()
    return int(number * _SIZE_MULTIPLIERS[unit])


@dataclass
class Config:
    """Runtime configuration for an eDocAPI application."""

    debug: bool = False
    max_file_size: int = 10 * 1024 * 1024  # 10 MB default
    temp_dir: Path | None = None
    max_files: int = 20

    # Internal: extra options for future use
    _extra: dict[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if isinstance(self.max_file_size, str):
            self.max_file_size = parse_size(self.max_file_size)
        if self.temp_dir is not None and not isinstance(self.temp_dir, Path):
            self.temp_dir = Path(self.temp_dir)

    @classmethod
    def from_kwargs(cls, **kwargs: Any) -> "Config":
        """Build a Config from App() keyword arguments."""
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore
        config_kwargs = {}
        extra = {}
        for key, value in kwargs.items():
            if key in known and key != "_extra":
                config_kwargs[key] = value
            else:
                extra[key] = value
        cfg = cls(**config_kwargs)
        cfg._extra = extra
        return cfg
