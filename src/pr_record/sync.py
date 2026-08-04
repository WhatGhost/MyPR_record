"""Synchronization service for merging GitHub results with persisted history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from pr_record.config import AppConfig
from pr_record.github import GitHubClient
from pr_record.models import PullRequest
from pr_record.storage import load_pull_requests, save_pull_requests

NEW_PULL_REQUEST_OVERLAP_DAYS = 1
TERMINAL_STATES = frozenset({"MERGED", "CLOSED"})


@dataclass(frozen=True, slots=True)
class SyncSummary:
    """Observable result of one synchronization run."""

    total: int
    fetched: int
    filtered: int
    changed: bool


def sync_from_github(
    config: AppConfig,
    token: str,
    *,
    full: bool = False,
) -> SyncSummary:
    """Fetch, merge, filter, and persist authored pull requests."""

    existing = load_pull_requests(config.data_file)
    client = GitHubClient(token)
    incremental = bool(existing) and not full
    created_since = _incremental_created_since(existing) if incremental else None

    if incremental and created_since is not None:
        open_ids = [
            pull_request.id
            for pull_request in existing
            if pull_request.normalized_state == "OPEN"
            and _should_include(pull_request, config)
        ]
        refreshed_open = client.get_pull_requests_by_ids(open_ids)
        recent = client.search_pull_requests_since(config.github_username, created_since)
        fetched_by_id = {pull_request.id: pull_request for pull_request in refreshed_open}
        fetched_by_id.update((pull_request.id, pull_request) for pull_request in recent)
        fetched = list(fetched_by_id.values())
    else:
        fetched = client.search_pull_requests(config.github_username)
        incremental = False

    merged = merge_pull_requests(
        existing,
        fetched,
        config,
        freeze_terminal=incremental,
    )
    included_fetched = sum(_should_include(pull_request, config) for pull_request in fetched)
    return SyncSummary(
        total=len(merged),
        fetched=len(fetched),
        filtered=len(fetched) - included_fetched,
        changed=save_pull_requests(config.data_file, merged),
    )


def merge_pull_requests(
    existing: list[PullRequest],
    fetched: list[PullRequest],
    config: AppConfig,
    *,
    freeze_terminal: bool = False,
) -> list[PullRequest]:
    """Upsert fetched PRs while preserving valid history absent from search results."""

    by_id = {
        pull_request.id: pull_request
        for pull_request in existing
        if _should_include(pull_request, config)
    }
    for pull_request in fetched:
        if not _should_include(pull_request, config):
            continue
        previous = by_id.get(pull_request.id)
        if (
            freeze_terminal
            and previous is not None
            and previous.normalized_state in TERMINAL_STATES
        ):
            continue
        by_id[pull_request.id] = pull_request

    pull_requests = list(by_id.values())
    pull_requests.sort(
        key=lambda pull_request: (pull_request.repository.casefold(), pull_request.number)
    )
    pull_requests.sort(key=lambda pull_request: pull_request.created_at, reverse=True)
    return pull_requests


def _should_include(pull_request: PullRequest, config: AppConfig) -> bool:
    if pull_request.is_private and not config.include_private:
        return False
    return not config.is_repository_excluded(pull_request.repository)


def _incremental_created_since(existing: list[PullRequest]) -> date | None:
    created_dates: list[date] = []
    for pull_request in existing:
        try:
            created_dates.append(date.fromisoformat(pull_request.created_at[:10]))
        except ValueError:
            return None
    if not created_dates:
        return None
    return max(created_dates) - timedelta(days=NEW_PULL_REQUEST_OVERLAP_DAYS)
