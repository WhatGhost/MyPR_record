from collections.abc import Mapping
from typing import Any

import pytest

from pr_record.github import GitHubAPIError, GitHubClient


def _node(
    node_id: str,
    *,
    repository: str = "octocat/hello-world",
    created_at: str = "2026-08-01T10:00:00Z",
) -> dict[str, Any]:
    return {
        "id": node_id,
        "number": int(node_id.removeprefix("PR_")),
        "title": f"Pull request {node_id}",
        "url": f"https://github.com/{repository}/pull/{node_id.removeprefix('PR_')}",
        "state": "OPEN",
        "isDraft": False,
        "createdAt": created_at,
        "updatedAt": created_at,
        "closedAt": None,
        "mergedAt": None,
        "additions": 10,
        "deletions": 2,
        "changedFiles": 1,
        "repository": {"nameWithOwner": repository, "isPrivate": False},
        "labels": {"nodes": [{"name": "enhancement"}]},
    }


def _response(
    nodes: list[dict[str, Any]],
    *,
    total: int | None = None,
    has_next: bool = False,
    cursor: str | None = None,
) -> dict[str, Any]:
    return {
        "search": {
            "issueCount": len(nodes) if total is None else total,
            "nodes": nodes,
            "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
        }
    }


def test_search_pull_requests_paginates_and_normalizes() -> None:
    cursors: list[str | None] = []

    def transport(query: str, variables: Mapping[str, Any]) -> Mapping[str, Any]:
        assert "PullRequestSearch" in query
        cursor = variables["cursor"]
        cursors.append(cursor)
        if cursor is None:
            return _response([_node("PR_1")], total=2, has_next=True, cursor="page-2")
        return _response([_node("PR_2")], total=2)

    pull_requests = GitHubClient("token", transport=transport).search_pull_requests("octocat")

    assert cursors == [None, "page-2"]
    assert [pull_request.id for pull_request in pull_requests] == ["PR_1", "PR_2"]
    assert pull_requests[0].repository == "octocat/hello-world"
    assert pull_requests[0].labels == ("enhancement",)


def test_search_pull_requests_partitions_large_result_by_year() -> None:
    search_queries: list[str] = []

    def transport(query: str, variables: Mapping[str, Any]) -> Mapping[str, Any]:
        assert "PullRequestSearch" in query
        search_query = str(variables["searchQuery"])
        search_queries.append(search_query)
        if "created:" not in search_query:
            return _response([_node("PR_1", created_at="2025-01-01T00:00:00Z")], total=1001)
        if "created:2025-" in search_query:
            return _response([_node("PR_1", created_at="2025-01-01T00:00:00Z")])
        return _response([])

    pull_requests = GitHubClient(
        "token",
        transport=transport,
        current_year=2026,
    ).search_pull_requests("octocat")

    assert [pull_request.id for pull_request in pull_requests] == ["PR_1"]
    assert len(search_queries) == 3
    assert "created:2025-01-01..2025-12-31" in search_queries[1]
    assert "created:2026-01-01..2026-12-31" in search_queries[2]


def test_search_pull_requests_rejects_invalid_username() -> None:
    with pytest.raises(ValueError, match="Invalid GitHub username"):
        GitHubClient("token").search_pull_requests("invalid user")


def test_search_pull_requests_requires_next_page_cursor() -> None:
    def transport(query: str, variables: Mapping[str, Any]) -> Mapping[str, Any]:
        assert "PullRequestSearch" in query
        assert variables["cursor"] is None
        return _response([_node("PR_1")], has_next=True, cursor=None)

    with pytest.raises(GitHubAPIError, match="omitted the cursor"):
        GitHubClient("token", transport=transport).search_pull_requests("octocat")


def test_search_pull_requests_splits_large_year_by_month() -> None:
    queries: list[str] = []

    def transport(query: str, variables: Mapping[str, Any]) -> Mapping[str, Any]:
        assert "PullRequestSearch" in query
        search_query = str(variables["searchQuery"])
        queries.append(search_query)
        if "created:" not in search_query:
            return _response([_node("PR_1")], total=1001)
        if "created:2026-01-01..2026-12-31" in search_query:
            return _response([_node("PR_1")], total=1001)
        if "created:2026-02-01..2026-02-28" in search_query:
            return _response([_node("PR_2", created_at="2026-02-01T00:00:00Z")])
        return _response([])

    pull_requests = GitHubClient(
        "token",
        transport=transport,
        current_year=2026,
    ).search_pull_requests("octocat")

    assert [pull_request.id for pull_request in pull_requests] == ["PR_2"]
    assert len(queries) == 14


def test_search_pull_requests_rejects_month_over_search_limit() -> None:
    def transport(query: str, variables: Mapping[str, Any]) -> Mapping[str, Any]:
        assert "PullRequestSearch" in query
        search_query = str(variables["searchQuery"])
        if "created:" not in search_query:
            return _response([_node("PR_1")], total=1001)
        return _response([_node("PR_1")], total=1001)

    with pytest.raises(GitHubAPIError, match="More than 1000 PRs"):
        GitHubClient(
            "token",
            transport=transport,
            current_year=2026,
        ).search_pull_requests("octocat")
