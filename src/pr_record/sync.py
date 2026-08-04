"""Synchronization service for merging GitHub results with persisted history."""

from __future__ import annotations

from dataclasses import dataclass

from pr_record.config import AppConfig
from pr_record.github import GitHubClient
from pr_record.models import PullRequest
from pr_record.storage import load_pull_requests, save_pull_requests


@dataclass(frozen=True, slots=True)
class SyncSummary:
    """Observable result of one synchronization run."""

    total: int
    fetched: int
    filtered: int
    changed: bool


def sync_from_github(config: AppConfig, token: str) -> SyncSummary:
    """Fetch, merge, filter, and persist authored pull requests."""

    existing = load_pull_requests(config.data_file)
    fetched = GitHubClient(token).search_pull_requests(config.github_username)
    merged = merge_pull_requests(existing, fetched, config)
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
) -> list[PullRequest]:
    """Upsert fetched PRs while preserving valid history absent from search results."""

    by_id = {
        pull_request.id: pull_request
        for pull_request in existing
        if _should_include(pull_request, config)
    }
    by_id.update(
        (pull_request.id, pull_request)
        for pull_request in fetched
        if _should_include(pull_request, config)
    )

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
