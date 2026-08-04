from pathlib import Path

import pytest

from pr_record.models import PullRequest
from pr_record.storage import DataFileError, load_notes, load_pull_requests, save_pull_requests


def _pull_request() -> PullRequest:
    return PullRequest(
        id="PR_1",
        repository="octocat/hello-world",
        number=7,
        title="Improve the greeting",
        url="https://github.com/octocat/hello-world/pull/7",
        state="MERGED",
        is_draft=False,
        is_private=False,
        created_at="2026-08-01T10:00:00Z",
        updated_at="2026-08-02T10:00:00Z",
        closed_at="2026-08-02T10:00:00Z",
        merged_at="2026-08-02T10:00:00Z",
        additions=12,
        deletions=3,
        changed_files=2,
        labels=("documentation",),
    )


def test_pull_request_json_round_trip_is_stable(tmp_path: Path) -> None:
    path = tmp_path / "data" / "prs.json"

    assert save_pull_requests(path, [_pull_request()])
    assert load_pull_requests(path) == [_pull_request()]
    assert not save_pull_requests(path, [_pull_request()])


def test_load_pull_requests_rejects_unknown_schema(tmp_path: Path) -> None:
    path = tmp_path / "prs.json"
    path.write_text('{"schema_version": 99, "pull_requests": []}', encoding="utf-8")

    with pytest.raises(DataFileError, match="Unsupported"):
        load_pull_requests(path)


def test_load_pull_requests_rejects_invalid_json_and_duplicate_ids(tmp_path: Path) -> None:
    path = tmp_path / "prs.json"
    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(DataFileError, match="not valid JSON"):
        load_pull_requests(path)

    pull_request = _pull_request().to_dict()
    path.write_text(
        __import__("json").dumps(
            {"schema_version": 1, "pull_requests": [pull_request, pull_request]}
        ),
        encoding="utf-8",
    )
    with pytest.raises(DataFileError, match="duplicate"):
        load_pull_requests(path)


def test_load_notes_supports_mapping_and_string_shorthand(tmp_path: Path) -> None:
    path = tmp_path / "notes.yml"
    path.write_text(
        """
octocat/hello-world#7:
  category: Documentation
  note: Improved the example.
  highlight: true
octocat/hello-world#8: Small follow-up.
""".lstrip(),
        encoding="utf-8",
    )

    notes = load_notes(path)

    assert notes["octocat/hello-world#7"].category == "Documentation"
    assert notes["octocat/hello-world#7"].highlight
    assert notes["octocat/hello-world#8"].note == "Small follow-up."
