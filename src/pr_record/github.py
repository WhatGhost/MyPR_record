"""Minimal GitHub GraphQL client for discovering authored pull requests."""

from __future__ import annotations

import calendar
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pr_record.models import PullRequest

GRAPHQL_ENDPOINT = "https://api.github.com/graphql"
SEARCH_RESULT_LIMIT = 1_000
NODE_LOOKUP_BATCH_SIZE = 100
GITHUB_FIRST_YEAR = 2008
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")

PULL_REQUEST_FRAGMENT = """
fragment PullRequestFields on PullRequest {
    id
    number
    title
    url
    state
    isDraft
    createdAt
    updatedAt
    closedAt
    mergedAt
    additions
    deletions
    changedFiles
    repository {
        nameWithOwner
        isPrivate
    }
    labels(first: 100) {
        nodes {
            name
        }
    }
}
""".strip()

PULL_REQUEST_SEARCH_OPERATION = """
query PullRequestSearch($searchQuery: String!, $cursor: String) {
    search(query: $searchQuery, type: ISSUE, first: 100, after: $cursor) {
        issueCount
        pageInfo {
            hasNextPage
            endCursor
        }
        nodes {
            ...PullRequestFields
        }
    }
}
""".strip()

PULL_REQUEST_NODES_OPERATION = """
query PullRequestNodes($ids: [ID!]!) {
    nodes(ids: $ids) {
        ...PullRequestFields
    }
}
""".strip()

PULL_REQUEST_SEARCH_QUERY = f"{PULL_REQUEST_SEARCH_OPERATION}\n\n{PULL_REQUEST_FRAGMENT}"
PULL_REQUEST_NODES_QUERY = f"{PULL_REQUEST_NODES_OPERATION}\n\n{PULL_REQUEST_FRAGMENT}"

GraphQLTransport = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]


class GitHubAPIError(RuntimeError):
    """Raised when GitHub cannot provide a complete, valid response."""


@dataclass(frozen=True, slots=True)
class _SearchWindowTooLarge(Exception):
    total_count: int
    earliest_year: int | None


class GitHubClient:
    """Query authored pull requests through GitHub's GraphQL API."""

    def __init__(
        self,
        token: str,
        *,
        transport: GraphQLTransport | None = None,
        current_year: int | None = None,
    ) -> None:
        if not token.strip():
            raise ValueError("A non-empty GitHub token is required")
        self._token = token
        self._transport = transport or self._post_graphql
        self._current_year = current_year or datetime.now(UTC).year

    def search_pull_requests(self, username: str) -> list[PullRequest]:
        """Return all pull requests authored by a GitHub username."""

        _validate_username(username)
        base_query = f"is:pr author:{username} sort:created-asc"
        try:
            return self._search_window(base_query)
        except _SearchWindowTooLarge as error:
            first_year = error.earliest_year or GITHUB_FIRST_YEAR
            return self._search_partitioned(base_query, first_year)

    def search_pull_requests_since(
        self,
        username: str,
        created_since: date,
    ) -> list[PullRequest]:
        """Return authored PRs created on or after a date, including overlap."""

        _validate_username(username)
        search_query = (
            f"is:pr author:{username} created:>={created_since.isoformat()} sort:created-asc"
        )
        try:
            return self._search_window(search_query)
        except _SearchWindowTooLarge as exc:
            raise GitHubAPIError(
                f"More than {SEARCH_RESULT_LIMIT} PRs were found since {created_since.isoformat()}"
            ) from exc

    def get_pull_requests_by_ids(self, node_ids: list[str]) -> list[PullRequest]:
        """Return PRs for GitHub node IDs in bounded GraphQL batches."""

        unique_ids = list(dict.fromkeys(node_ids))
        pull_requests: list[PullRequest] = []
        for offset in range(0, len(unique_ids), NODE_LOOKUP_BATCH_SIZE):
            batch = unique_ids[offset : offset + NODE_LOOKUP_BATCH_SIZE]
            response = self._transport(PULL_REQUEST_NODES_QUERY, {"ids": batch})
            raw_nodes = response.get("nodes")
            if not isinstance(raw_nodes, list):
                raise GitHubAPIError("GitHub response field data.nodes must be a list")
            for raw_node in raw_nodes:
                if raw_node is not None:
                    pull_requests.append(
                        _parse_pull_request(_require_mapping(raw_node, "PR node"))
                    )
        return pull_requests

    def _search_partitioned(self, base_query: str, first_year: int) -> list[PullRequest]:
        pull_requests: dict[str, PullRequest] = {}
        for year in range(first_year, self._current_year + 1):
            year_query = f"{base_query} created:{year:04d}-01-01..{year:04d}-12-31"
            try:
                year_results = self._search_window(year_query)
            except _SearchWindowTooLarge:
                year_results = self._search_year_by_month(base_query, year)
            pull_requests.update((pull_request.id, pull_request) for pull_request in year_results)
        return list(pull_requests.values())

    def _search_year_by_month(self, base_query: str, year: int) -> list[PullRequest]:
        pull_requests: dict[str, PullRequest] = {}
        for month in range(1, 13):
            last_day = calendar.monthrange(year, month)[1]
            month_query = (
                f"{base_query} "
                f"created:{year:04d}-{month:02d}-01..{year:04d}-{month:02d}-{last_day:02d}"
            )
            try:
                month_results = self._search_window(month_query)
            except _SearchWindowTooLarge as exc:
                raise GitHubAPIError(
                    f"More than {SEARCH_RESULT_LIMIT} PRs were found in {year:04d}-{month:02d}; "
                    "the search window must be split more narrowly"
                ) from exc
            pull_requests.update((pull_request.id, pull_request) for pull_request in month_results)
        return list(pull_requests.values())

    def _search_window(self, search_query: str) -> list[PullRequest]:
        pull_requests: list[PullRequest] = []
        cursor: str | None = None
        first_page = True

        while True:
            response = self._transport(
                PULL_REQUEST_SEARCH_QUERY,
                {"searchQuery": search_query, "cursor": cursor},
            )
            search = _require_mapping(response.get("search"), "data.search")
            raw_nodes = search.get("nodes")
            if not isinstance(raw_nodes, list):
                raise GitHubAPIError("GitHub response field data.search.nodes must be a list")

            if first_page:
                total_count = _require_int(search.get("issueCount"), "data.search.issueCount")
                if total_count > SEARCH_RESULT_LIMIT:
                    raise _SearchWindowTooLarge(total_count, _earliest_year(raw_nodes))
                first_page = False

            for raw_node in raw_nodes:
                if raw_node is not None:
                    pull_requests.append(_parse_pull_request(_require_mapping(raw_node, "PR node")))

            page_info = _require_mapping(search.get("pageInfo"), "data.search.pageInfo")
            has_next_page = page_info.get("hasNextPage")
            if not isinstance(has_next_page, bool):
                raise GitHubAPIError("GitHub response has an invalid hasNextPage value")
            if not has_next_page:
                break

            end_cursor = page_info.get("endCursor")
            if not isinstance(end_cursor, str) or not end_cursor:
                raise GitHubAPIError("GitHub response omitted the cursor for the next page")
            cursor = end_cursor

        return pull_requests

    def _post_graphql(
        self,
        query: str,
        variables: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        body = json.dumps({"query": query, "variables": dict(variables)}).encode("utf-8")
        request = Request(
            GRAPHQL_ENDPOINT,
            data=body,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "User-Agent": "pr-record/0.1",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310
                payload: Any = json.load(response)
        except HTTPError as exc:
            raise GitHubAPIError(f"GitHub API returned HTTP {exc.code}") from exc
        except URLError as exc:
            raise GitHubAPIError(f"Unable to reach GitHub API: {exc.reason}") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise GitHubAPIError("GitHub API returned invalid JSON") from exc

        root = _require_mapping(payload, "GraphQL response")
        errors = root.get("errors")
        if errors:
            raise GitHubAPIError(f"GitHub GraphQL errors: {_format_graphql_errors(errors)}")
        return _require_mapping(root.get("data"), "GraphQL response data")


def _parse_pull_request(node: Mapping[str, Any]) -> PullRequest:
    repository = _require_mapping(node.get("repository"), "PR repository")
    labels_connection = _require_mapping(node.get("labels"), "PR labels")
    raw_labels = labels_connection.get("nodes")
    if not isinstance(raw_labels, list):
        raise GitHubAPIError("PR labels.nodes must be a list")

    labels: list[str] = []
    for raw_label in raw_labels:
        label = _require_mapping(raw_label, "PR label")
        labels.append(_require_string(label.get("name"), "PR label name"))

    return PullRequest(
        id=_require_string(node.get("id"), "PR id"),
        repository=_require_string(repository.get("nameWithOwner"), "PR repository name"),
        number=_require_int(node.get("number"), "PR number"),
        title=_require_string(node.get("title"), "PR title"),
        url=_require_string(node.get("url"), "PR URL"),
        state=_require_string(node.get("state"), "PR state"),
        is_draft=_require_bool(node.get("isDraft"), "PR isDraft"),
        is_private=_require_bool(repository.get("isPrivate"), "PR repository isPrivate"),
        created_at=_require_string(node.get("createdAt"), "PR createdAt"),
        updated_at=_require_string(node.get("updatedAt"), "PR updatedAt"),
        closed_at=_optional_string(node.get("closedAt"), "PR closedAt"),
        merged_at=_optional_string(node.get("mergedAt"), "PR mergedAt"),
        additions=_require_int(node.get("additions"), "PR additions"),
        deletions=_require_int(node.get("deletions"), "PR deletions"),
        changed_files=_require_int(node.get("changedFiles"), "PR changedFiles"),
        labels=tuple(sorted(labels, key=str.casefold)),
    )


def _validate_username(username: str) -> None:
    if not USERNAME_PATTERN.fullmatch(username):
        raise ValueError(f"Invalid GitHub username: {username!r}")


def _earliest_year(nodes: list[Any]) -> int | None:
    for raw_node in nodes:
        if isinstance(raw_node, Mapping):
            created_at = raw_node.get("createdAt")
            if isinstance(created_at, str) and len(created_at) >= 4:
                try:
                    return int(created_at[:4])
                except ValueError:
                    continue
    return None


def _format_graphql_errors(errors: Any) -> str:
    if not isinstance(errors, list):
        return str(errors)
    messages = [
        str(error.get("message", error)) if isinstance(error, Mapping) else str(error)
        for error in errors
    ]
    return "; ".join(messages)


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GitHubAPIError(f"{name} must be an object")
    return value


def _require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise GitHubAPIError(f"{name} must be a non-empty string")
    return value


def _optional_string(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, name)


def _require_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise GitHubAPIError(f"{name} must be an integer")
    return value


def _require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise GitHubAPIError(f"{name} must be a boolean")
    return value
