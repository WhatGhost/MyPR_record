"""Deterministic Markdown rendering for the public PR record."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pr_record.config import AppConfig
from pr_record.models import PullRequest, PullRequestNote
from pr_record.storage import load_notes, load_pull_requests, write_text_if_changed
from pr_record.sync import merge_pull_requests

GENERATED_START = "<!-- pr-record:generated:start -->"
GENERATED_END = "<!-- pr-record:generated:end -->"


class ReadmeTemplateError(ValueError):
    """Raised when an existing README has malformed generated markers."""


@dataclass(frozen=True, slots=True)
class PullRequestStats:
    """Aggregate statistics for the included pull requests."""

    total: int
    merged: int
    open: int
    closed: int
    draft: int
    repositories: int
    additions: int
    deletions: int
    changed_files: int

    @property
    def merge_rate(self) -> float | None:
        """Return the terminal-PR merge rate, excluding still-open PRs."""

        terminal_count = self.merged + self.closed
        if terminal_count == 0:
            return None
        return self.merged / terminal_count

    @property
    def overall_merge_rate(self) -> float | None:
        """Return merged PRs divided by all included PRs, including open PRs."""

        if self.total == 0:
            return None
        return self.merged / self.total


def calculate_stats(pull_requests: list[PullRequest]) -> PullRequestStats:
    """Calculate aggregate statistics from included PRs."""

    states = Counter(pull_request.normalized_state for pull_request in pull_requests)
    return PullRequestStats(
        total=len(pull_requests),
        merged=states["MERGED"],
        open=states["OPEN"],
        closed=states["CLOSED"],
        draft=sum(pull_request.is_draft for pull_request in pull_requests),
        repositories=len({pull_request.repository.casefold() for pull_request in pull_requests}),
        additions=sum(pull_request.additions for pull_request in pull_requests),
        deletions=sum(pull_request.deletions for pull_request in pull_requests),
        changed_files=sum(pull_request.changed_files for pull_request in pull_requests),
    )


def render_from_files(config: AppConfig) -> bool:
    """Load local data, reapply filters, and update the configured README."""

    pull_requests = merge_pull_requests(
        load_pull_requests(config.data_file),
        [],
        config,
    )
    notes = load_notes(config.notes_file)
    generated = build_generated_markdown(pull_requests, notes)
    return update_readme(config.readme_file, generated)


def build_generated_markdown(
    pull_requests: list[PullRequest],
    notes: dict[str, PullRequestNote],
) -> str:
    """Build the complete generated Markdown section."""

    stats = calculate_stats(pull_requests)
    merge_rate = _display_rate(stats.merge_rate)
    overall_merge_rate = _display_rate(stats.overall_merge_rate)
    lines = [
        "## 贡献概览",
        "",
        (
            "| PR 总数 | 已合并 | Open | 未合并关闭 | Draft | 贡献仓库 | "
            "已结束 PR 合并率 | 总体合并率（含 Open） |"
        ),
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        (
            f"| {stats.total} | {stats.merged} | {stats.open} | {stats.closed} | "
            f"{stats.draft} | {stats.repositories} | {merge_rate} | {overall_merge_rate} |"
        ),
        "",
        "| 新增代码 | 删除代码 | 变更文件 |",
        "| ---: | ---: | ---: |",
        f"| +{stats.additions:,} | -{stats.deletions:,} | {stats.changed_files:,} |",
        "",
        "## 年度统计",
        "",
    ]

    by_year = _group_by_year(pull_requests)
    if by_year:
        lines.extend(
            [
                "| 年份 | PR | 已合并 | Open | 未合并关闭 | 贡献仓库 |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for year, year_pull_requests in by_year.items():
            year_stats = calculate_stats(year_pull_requests)
            lines.append(
                f"| {year} | {year_stats.total} | {year_stats.merged} | {year_stats.open} | "
                f"{year_stats.closed} | {year_stats.repositories} |"
            )
    else:
        lines.append("> 尚未同步到符合条件的 PR。")

    lines.extend(["", "## 仓库统计", ""])
    by_repository = _group_by_repository(pull_requests)
    if by_repository:
        lines.extend(
            [
                (
                    "| 仓库 | PR | 已合并 | Open | 未合并关闭 | Draft | "
                    "已结束 PR 合并率 | 总体合并率（含 Open） |"
                ),
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for repository, repository_pull_requests in by_repository:
            repository_stats = calculate_stats(repository_pull_requests)
            repository_name = _escape_table_text(repository)
            repository_url = f"https://github.com/{repository}"
            lines.append(
                f"| [{repository_name}]({repository_url}) "
                f"| {repository_stats.total} "
                f"| {repository_stats.merged} "
                f"| {repository_stats.open} "
                f"| {repository_stats.closed} "
                f"| {repository_stats.draft} "
                f"| {_display_rate(repository_stats.merge_rate)} "
                f"| {_display_rate(repository_stats.overall_merge_rate)} |"
            )
    else:
        lines.append("> 尚未同步到符合条件的 PR。")

    lines.extend(["", "## PR 明细", ""])
    if not by_year:
        lines.append("首次配置完成后，在 GitHub Actions 页面手动运行一次同步工作流。")
        return "\n".join(lines).rstrip() + "\n"

    for year, year_pull_requests in by_year.items():
        lines.extend(
            [
                f"### {year}",
                "",
                (
                    "| 仓库 | Pull Request | 状态 | 创建日期 | 合并日期 | "
                    "代码变更 | 标签 | 分类 | 备注 |"
                ),
                "| --- | --- | --- | --- | --- | ---: | --- | --- | --- |",
            ]
        )
        for pull_request in year_pull_requests:
            note = notes.get(pull_request.key, PullRequestNote())
            title_prefix = "⭐ " if note.highlight else ""
            title = _escape_link_text(pull_request.title)
            repository = _escape_table_text(pull_request.repository)
            repository_url = f"https://github.com/{pull_request.repository}"
            labels = ", ".join(pull_request.labels) or "—"
            changes = f"+{pull_request.additions:,} / -{pull_request.deletions:,}"
            lines.append(
                f"| [{repository}]({repository_url}) "
                f"| {title_prefix}[#{pull_request.number} {title}]({pull_request.url}) "
                f"| {_display_state(pull_request)} "
                f"| {_display_date(pull_request.created_at)} "
                f"| {_display_date(pull_request.merged_at)} "
                f"| {changes} "
                f"| {_escape_table_text(labels)} "
                f"| {_escape_table_text(note.category) or '—'} "
                f"| {_escape_table_text(note.note) or '—'} |"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def update_readme(path: Path, generated: str) -> bool:
    """Replace only the protected generated section of a README."""

    existing = path.read_text(encoding="utf-8") if path.exists() else _new_readme_template()

    start_count = existing.count(GENERATED_START)
    end_count = existing.count(GENERATED_END)
    if start_count != 1 or end_count != 1:
        raise ReadmeTemplateError(
            "README must contain exactly one generated start marker and one end marker"
        )

    start_index = existing.index(GENERATED_START) + len(GENERATED_START)
    end_index = existing.index(GENERATED_END)
    if start_index > end_index:
        raise ReadmeTemplateError("README generated markers are in the wrong order")

    updated = f"{existing[:start_index]}\n\n{generated.rstrip()}\n\n{existing[end_index:]}"
    return write_text_if_changed(path, updated)


def _group_by_year(pull_requests: list[PullRequest]) -> dict[str, list[PullRequest]]:
    result: dict[str, list[PullRequest]] = {}
    for pull_request in pull_requests:
        year = pull_request.created_at[:4]
        if len(year) != 4 or not year.isdigit():
            year = "未知年份"
        result.setdefault(year, []).append(pull_request)
    return result


def _group_by_repository(
    pull_requests: list[PullRequest],
) -> list[tuple[str, list[PullRequest]]]:
    grouped: dict[str, list[PullRequest]] = {}
    for pull_request in pull_requests:
        grouped.setdefault(pull_request.repository.casefold(), []).append(pull_request)

    result = [
        (repository_pull_requests[0].repository, repository_pull_requests)
        for repository_pull_requests in grouped.values()
    ]
    result.sort(key=lambda item: (-len(item[1]), item[0].casefold()))
    return result


def _display_state(pull_request: PullRequest) -> str:
    if pull_request.is_draft and pull_request.normalized_state == "OPEN":
        return "⚪ Draft"
    return {
        "MERGED": "🟣 Merged",
        "OPEN": "🟢 Open",
        "CLOSED": "🔴 Closed",
    }.get(pull_request.normalized_state, pull_request.normalized_state)


def _display_date(timestamp: str | None) -> str:
    if timestamp is None:
        return "—"
    return timestamp[:10] if len(timestamp) >= 10 else timestamp


def _display_rate(rate: float | None) -> str:
    return "—" if rate is None else f"{rate:.1%}"


def _escape_table_text(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return (
        normalized.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("|", "\\|")
        .replace("\n", "<br>")
    )


def _escape_link_text(value: str) -> str:
    return _escape_table_text(value).replace("[", "\\[").replace("]", "\\]")


def _new_readme_template() -> str:
    return f"""# My PR Record

自动收集并展示由 GitHub Actions 同步的开源 Pull Request。

{GENERATED_START}
{GENERATED_END}

> 两个注释标记之间的内容由程序生成，请勿手动修改。
"""
