from pathlib import Path

import pytest

from pr_record.models import PullRequest, PullRequestNote
from pr_record.render import (
    GENERATED_END,
    GENERATED_START,
    ReadmeTemplateError,
    build_generated_markdown,
    calculate_stats,
    update_readme,
)


def _pull_request(
    node_id: str,
    *,
    state: str = "OPEN",
    merged_at: str | None = None,
    is_draft: bool = False,
    title: str = "Improve docs",
    created_at: str = "2026-08-01T10:00:00Z",
) -> PullRequest:
    number = int(node_id.removeprefix("PR_"))
    return PullRequest(
        id=node_id,
        repository="octocat/hello-world",
        number=number,
        title=title,
        url=f"https://github.com/octocat/hello-world/pull/{number}",
        state=state,
        is_draft=is_draft,
        is_private=False,
        created_at=created_at,
        updated_at=created_at,
        closed_at=merged_at,
        merged_at=merged_at,
        additions=10,
        deletions=2,
        changed_files=1,
        labels=("documentation",),
    )


def test_calculate_stats_excludes_open_prs_from_merge_rate() -> None:
    pull_requests = [
        _pull_request("PR_1", state="MERGED", merged_at="2026-08-02T00:00:00Z"),
        _pull_request("PR_2", state="CLOSED"),
        _pull_request("PR_3", is_draft=True),
    ]

    stats = calculate_stats(pull_requests)

    assert stats.total == 3
    assert stats.merged == 1
    assert stats.open == 1
    assert stats.closed == 1
    assert stats.draft == 1
    assert stats.merge_rate == 0.5
    assert stats.overall_merge_rate == pytest.approx(1 / 3)


def test_generated_markdown_uses_dates_and_escapes_table_content() -> None:
    pull_request = _pull_request(
        "PR_7",
        state="MERGED",
        merged_at="2026-08-03T12:30:00Z",
        title="Fix [table] | formatting",
    )
    notes = {
        pull_request.key: PullRequestNote(
            category="Docs | UX",
            note="First line\nSecond line",
            highlight=True,
        )
    }

    markdown = build_generated_markdown([pull_request], notes)

    assert "⭐ [#7 Fix \\[table\\] \\| formatting]" in markdown
    assert (
        "| 仓库 | Pull Request | 状态 | 创建日期 | 合并日期 | "
        "代码变更 | 标签 | 分类 | 备注 |" in markdown
    )
    assert "| 2026-08-01 | 2026-08-03 | +10 / -2 |" in markdown
    assert "| 日期 |" not in markdown
    assert "Docs \\| UX" in markdown
    assert "First line<br>Second line" in markdown


def test_generated_markdown_shows_missing_merge_date_for_open_pr() -> None:
    markdown = build_generated_markdown([_pull_request("PR_9")], {})

    assert "| 2026-08-01 | — | +10 / -2 |" in markdown
    assert "| 1 | 0 | 1 | 0 | 0 | 1 | — | 0.0% |" in markdown


def test_generated_markdown_escapes_html_and_marker_injection() -> None:
    pull_request = _pull_request(
        "PR_8",
        title=f"Do not inject {GENERATED_END} & HTML",
    )

    markdown = build_generated_markdown([pull_request], {})

    assert GENERATED_END not in markdown
    assert "&lt;!-- pr-record:generated:end --&gt; &amp; HTML" in markdown


def test_update_readme_preserves_manual_content_and_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "README.md"
    path.write_text(
        f"# Manual title\n\n{GENERATED_START}\nold\n{GENERATED_END}\n\nManual footer\n",
        encoding="utf-8",
    )

    assert update_readme(path, "new generated content\n")
    assert not update_readme(path, "new generated content\n")
    content = path.read_text(encoding="utf-8")
    assert content.startswith("# Manual title")
    assert "old" not in content
    assert "new generated content" in content
    assert content.endswith("Manual footer\n")


def test_update_readme_rejects_malformed_markers(tmp_path: Path) -> None:
    path = tmp_path / "README.md"
    path.write_text(f"# Missing end\n{GENERATED_START}\n", encoding="utf-8")

    with pytest.raises(ReadmeTemplateError, match="exactly one"):
        update_readme(path, "generated")


def test_update_readme_creates_a_new_template(tmp_path: Path) -> None:
    path = tmp_path / "README.md"

    assert update_readme(path, "generated")
    content = path.read_text(encoding="utf-8")
    assert content.startswith("# My PR Record")
    assert content.count(GENERATED_START) == 1
    assert content.count(GENERATED_END) == 1
    assert "generated" in content
