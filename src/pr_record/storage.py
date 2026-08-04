"""Persistence helpers for generated PR data and manual notes."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from pr_record.models import PullRequest, PullRequestNote

SCHEMA_VERSION = 1


class DataFileError(ValueError):
    """Raised when persisted application data is invalid."""


def load_pull_requests(path: Path) -> list[PullRequest]:
    """Load normalized pull requests, returning an empty list when absent."""

    if not path.exists():
        return []

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DataFileError(f"PR data is not valid JSON: {path}") from exc

    if not isinstance(raw, dict):
        raise DataFileError("PR data root must be an object")
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise DataFileError(f"Unsupported PR data schema: {raw.get('schema_version')!r}")

    values = raw.get("pull_requests")
    if not isinstance(values, list):
        raise DataFileError("pull_requests must be a list")

    try:
        pull_requests = [PullRequest.from_dict(value) for value in values]
    except (KeyError, TypeError, ValueError) as exc:
        raise DataFileError("A persisted pull request is invalid") from exc

    ids = [pull_request.id for pull_request in pull_requests]
    if len(ids) != len(set(ids)):
        raise DataFileError("PR data contains duplicate GitHub node IDs")
    return pull_requests


def save_pull_requests(path: Path, pull_requests: list[PullRequest]) -> bool:
    """Persist records deterministically and report whether the file changed."""

    payload = {
        "schema_version": SCHEMA_VERSION,
        "pull_requests": [pull_request.to_dict() for pull_request in pull_requests],
    }
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    return write_text_if_changed(path, content)


def load_notes(path: Path) -> dict[str, PullRequestNote]:
    """Load optional user-maintained PR notes from YAML."""

    if not path.exists():
        return {}

    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise DataFileError(f"Notes are not valid YAML: {path}") from exc

    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise DataFileError("Notes root must be a mapping")

    try:
        return {str(key): PullRequestNote.from_value(value) for key, value in raw.items()}
    except ValueError as exc:
        raise DataFileError("A PR note is invalid") from exc


def write_text_if_changed(path: Path, content: str) -> bool:
    """Atomically write UTF-8 text only when its contents changed."""

    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_file.write(content)
            temporary_path = Path(temporary_file.name)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return True
