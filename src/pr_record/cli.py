"""Command-line entry points shared by local use and GitHub Actions."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from pr_record.config import ConfigError, load_config
from pr_record.github import GitHubAPIError
from pr_record.render import ReadmeTemplateError, render_from_files
from pr_record.storage import DataFileError
from pr_record.sync import sync_from_github


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""

    parser = argparse.ArgumentParser(description="Synchronize and render authored GitHub PRs.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.yml"),
        help="Path to the YAML configuration file (default: config.yml).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("render", help="Render README from the local data file.")
    sync_parser = subparsers.add_parser(
        "sync",
        help="Fetch PRs, persist them, and render README.",
    )
    sync_parser.add_argument(
        "--full",
        action="store_true",
        help="Refresh all authored PRs instead of only new and open PRs.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run a CLI command and return its process exit code."""

    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "render":
            changed = render_from_files(config)
            print("README updated." if changed else "README is already up to date.")
            return 0

        token = os.environ.get("PR_READ_TOKEN", "").strip()
        if not token:
            raise ConfigError("PR_READ_TOKEN is required for the sync command")
        summary = sync_from_github(config, token, full=args.full)
        readme_changed = render_from_files(config)
        print(
            f"Synchronized {summary.fetched} PRs; retained {summary.total}; "
            f"filtered {summary.filtered}."
        )
        if summary.changed or readme_changed:
            print("Generated files updated.")
        else:
            print("Generated files are already up to date.")
        return 0
    except (ConfigError, DataFileError, GitHubAPIError, ReadmeTemplateError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
