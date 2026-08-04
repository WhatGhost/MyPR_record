from datetime import date
from pathlib import Path

import pr_record.sync as sync_module
from pr_record.config import AppConfig
from pr_record.models import PullRequest
from pr_record.storage import load_pull_requests, save_pull_requests
from pr_record.sync import merge_pull_requests, sync_from_github


def _config(*excluded: str, include_private: bool = False) -> AppConfig:
    return AppConfig(
        github_username="WhatGhost",
        include_private=include_private,
        excluded_repositories=excluded,
        data_file=Path("data/prs.json"),
        notes_file=Path("notes.yml"),
        readme_file=Path("README.md"),
    )


def _pull_request(
    node_id: str,
    repository: str,
    *,
    state: str = "OPEN",
    merged_at: str | None = None,
    is_private: bool = False,
    created_at: str = "2026-08-01T10:00:00Z",
) -> PullRequest:
    return PullRequest(
        id=node_id,
        repository=repository,
        number=int(node_id.removeprefix("PR_")),
        title=f"Pull request {node_id}",
        url=f"https://github.com/{repository}/pull/{node_id.removeprefix('PR_')}",
        state=state,
        is_draft=False,
        is_private=is_private,
        created_at=created_at,
        updated_at=created_at,
        closed_at=merged_at,
        merged_at=merged_at,
        additions=10,
        deletions=2,
        changed_files=1,
        labels=(),
    )


def test_merge_updates_fetched_and_preserves_missing_history() -> None:
    existing = [
        _pull_request("PR_1", "octocat/one"),
        _pull_request("PR_2", "octocat/two", created_at="2025-01-01T00:00:00Z"),
    ]
    fetched = [
        _pull_request(
            "PR_1",
            "octocat/one",
            state="MERGED",
            merged_at="2026-08-02T10:00:00Z",
        )
    ]

    merged = merge_pull_requests(existing, fetched, _config())

    assert [pull_request.id for pull_request in merged] == ["PR_1", "PR_2"]
    assert merged[0].normalized_state == "MERGED"


def test_merge_freezes_existing_terminal_records_only_when_requested() -> None:
    terminal = _pull_request(
        "PR_1",
        "octocat/one",
        state="MERGED",
        merged_at="2026-08-02T10:00:00Z",
    )
    contradictory = _pull_request("PR_1", "octocat/one")

    incremental = merge_pull_requests(
        [terminal],
        [contradictory],
        _config(),
        freeze_terminal=True,
    )
    full = merge_pull_requests([terminal], [contradictory], _config())

    assert incremental == [terminal]
    assert full == [contradictory]


def test_merge_removes_exact_wildcard_and_private_exclusions() -> None:
    pull_requests = [
        _pull_request("PR_1", "WhatGhost/MyPR_record"),
        _pull_request("PR_2", "labs/experiment-one"),
        _pull_request("PR_3", "private/secret", is_private=True),
        _pull_request("PR_4", "octocat/kept"),
    ]

    merged = merge_pull_requests(
        pull_requests,
        [],
        _config("whatghost/mypr_record", "labs/*"),
    )

    assert [pull_request.repository for pull_request in merged] == ["octocat/kept"]


def test_sync_from_github_filters_and_persists(tmp_path: Path, monkeypatch) -> None:
    config = AppConfig(
        github_username="WhatGhost",
        include_private=False,
        excluded_repositories=("excluded/*",),
        data_file=tmp_path / "data/prs.json",
        notes_file=tmp_path / "notes.yml",
        readme_file=tmp_path / "README.md",
    )
    fetched = [
        _pull_request("PR_1", "octocat/kept"),
        _pull_request("PR_2", "excluded/repository"),
    ]

    class FakeGitHubClient:
        def __init__(self, token: str) -> None:
            assert token == "read-token"

        def search_pull_requests(self, username: str) -> list[PullRequest]:
            assert username == "WhatGhost"
            return fetched

    monkeypatch.setattr(sync_module, "GitHubClient", FakeGitHubClient)

    summary = sync_from_github(config, "read-token")

    assert summary.total == 1
    assert summary.fetched == 2
    assert summary.filtered == 1
    assert summary.changed
    assert load_pull_requests(config.data_file) == [fetched[0]]


def test_incremental_sync_refreshes_open_adds_new_and_freezes_terminal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = AppConfig(
        github_username="WhatGhost",
        include_private=False,
        excluded_repositories=(),
        data_file=tmp_path / "data/prs.json",
        notes_file=tmp_path / "notes.yml",
        readme_file=tmp_path / "README.md",
    )
    existing_open = _pull_request("PR_1", "octocat/open")
    existing_terminal = _pull_request(
        "PR_2",
        "octocat/terminal",
        state="MERGED",
        merged_at="2026-07-02T00:00:00Z",
        created_at="2026-07-01T00:00:00Z",
    )
    save_pull_requests(config.data_file, [existing_open, existing_terminal])

    refreshed_open = _pull_request(
        "PR_1",
        "octocat/open",
        state="MERGED",
        merged_at="2026-08-03T00:00:00Z",
    )
    contradictory_terminal = _pull_request(
        "PR_2",
        "octocat/terminal",
        created_at="2026-07-01T00:00:00Z",
    )
    new_pull_request = _pull_request(
        "PR_3",
        "octocat/new",
        created_at="2026-08-04T00:00:00Z",
    )

    class FakeGitHubClient:
        def __init__(self, token: str) -> None:
            assert token == "read-token"

        def search_pull_requests(self, username: str) -> list[PullRequest]:
            raise AssertionError(
                f"incremental sync for {username} must not perform a full search"
            )

        def get_pull_requests_by_ids(self, node_ids: list[str]) -> list[PullRequest]:
            assert node_ids == ["PR_1"]
            return [refreshed_open]

        def search_pull_requests_since(
            self,
            username: str,
            created_since: date,
        ) -> list[PullRequest]:
            assert username == "WhatGhost"
            assert created_since == date(2026, 7, 31)
            return [contradictory_terminal, new_pull_request]

    monkeypatch.setattr(sync_module, "GitHubClient", FakeGitHubClient)

    summary = sync_from_github(config, "read-token")
    persisted = {
        pull_request.id: pull_request
        for pull_request in load_pull_requests(config.data_file)
    }

    assert summary.fetched == 3
    assert persisted["PR_1"] == refreshed_open
    assert persisted["PR_2"] == existing_terminal
    assert persisted["PR_3"] == new_pull_request


def test_explicit_full_sync_refreshes_existing_terminal_records(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = AppConfig(
        github_username="WhatGhost",
        include_private=False,
        excluded_repositories=(),
        data_file=tmp_path / "data/prs.json",
        notes_file=tmp_path / "notes.yml",
        readme_file=tmp_path / "README.md",
    )
    terminal = _pull_request(
        "PR_1",
        "octocat/one",
        state="MERGED",
        merged_at="2026-08-02T00:00:00Z",
    )
    corrected = _pull_request("PR_1", "octocat/renamed")
    save_pull_requests(config.data_file, [terminal])

    class FakeGitHubClient:
        def __init__(self, token: str) -> None:
            assert token == "read-token"

        def search_pull_requests(self, username: str) -> list[PullRequest]:
            assert username == "WhatGhost"
            return [corrected]

        def get_pull_requests_by_ids(self, node_ids: list[str]) -> list[PullRequest]:
            raise AssertionError(
                f"full sync must not refresh only open PRs: {node_ids!r}"
            )

        def search_pull_requests_since(
            self,
            username: str,
            created_since: date,
        ) -> list[PullRequest]:
            raise AssertionError(
                f"full sync for {username} must not use date window {created_since}"
            )

    monkeypatch.setattr(sync_module, "GitHubClient", FakeGitHubClient)

    sync_from_github(config, "read-token", full=True)

    assert load_pull_requests(config.data_file) == [corrected]


def test_merge_keeps_private_pull_requests_when_enabled() -> None:
    private_pull_request = _pull_request("PR_1", "private/allowed", is_private=True)

    merged = merge_pull_requests(
        [],
        [private_pull_request],
        _config(include_private=True),
    )

    assert merged == [private_pull_request]
