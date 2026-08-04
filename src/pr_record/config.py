"""Configuration loading and repository exclusion rules."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when the application configuration is invalid."""


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Validated application configuration."""

    github_username: str
    include_private: bool
    excluded_repositories: tuple[str, ...]
    data_file: Path
    notes_file: Path
    readme_file: Path

    def is_repository_excluded(self, repository: str) -> bool:
        """Return whether an owner/repository name matches an exclusion pattern."""

        normalized_repository = repository.strip().casefold()
        return any(
            fnmatchcase(normalized_repository, pattern.casefold())
            for pattern in self.excluded_repositories
        )


def load_config(path: Path) -> AppConfig:
    """Load and validate a YAML configuration file."""

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Configuration file does not exist: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Configuration file is not valid YAML: {path}") from exc

    root = _require_mapping(raw, "configuration")
    github = _require_mapping(root.get("github"), "github")
    files = _require_mapping(root.get("files"), "files")

    username = _require_non_empty_string(github.get("username"), "github.username")
    include_private = github.get("include_private", False)
    if not isinstance(include_private, bool):
        raise ConfigError("github.include_private must be true or false")

    excluded = github.get("excluded_repositories", [])
    if not isinstance(excluded, list):
        raise ConfigError("github.excluded_repositories must be a list")

    patterns: list[str] = []
    for index, pattern in enumerate(excluded):
        patterns.append(
            _require_non_empty_string(pattern, f"github.excluded_repositories[{index}]")
        )

    base_directory = path.resolve().parent
    return AppConfig(
        github_username=username,
        include_private=include_private,
        excluded_repositories=tuple(patterns),
        data_file=_resolve_file(base_directory, files.get("data"), "files.data"),
        notes_file=_resolve_file(base_directory, files.get("notes"), "files.notes"),
        readme_file=_resolve_file(base_directory, files.get("readme"), "files.readme"),
    )


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigError(f"{name} must be a mapping")
    return value


def _require_non_empty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{name} must be a non-empty string")
    return value.strip()


def _resolve_file(base_directory: Path, value: Any, name: str) -> Path:
    configured_path = Path(_require_non_empty_string(value, name))
    if configured_path.is_absolute():
        return configured_path
    return base_directory / configured_path
