"""Domain models for pull requests and user-authored notes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PullRequest:
    """A normalized pull request returned by GitHub."""

    id: str
    repository: str
    number: int
    title: str
    url: str
    state: str
    is_draft: bool
    is_private: bool
    created_at: str
    updated_at: str
    closed_at: str | None
    merged_at: str | None
    additions: int
    deletions: int
    changed_files: int
    labels: tuple[str, ...]

    @property
    def key(self) -> str:
        """Return a stable, human-readable key for attaching notes."""

        return f"{self.repository}#{self.number}"

    @property
    def normalized_state(self) -> str:
        """Return one of OPEN, CLOSED, or MERGED."""

        if self.merged_at is not None or self.state.casefold() == "merged":
            return "MERGED"
        return self.state.upper()

    def to_dict(self) -> dict[str, Any]:
        """Convert the model to a JSON-serializable dictionary."""

        result = asdict(self)
        result["labels"] = list(self.labels)
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> PullRequest:
        """Create a model from persisted normalized data."""

        return cls(
            id=str(value["id"]),
            repository=str(value["repository"]),
            number=int(value["number"]),
            title=str(value["title"]),
            url=str(value["url"]),
            state=str(value["state"]),
            is_draft=bool(value["is_draft"]),
            is_private=bool(value["is_private"]),
            created_at=str(value["created_at"]),
            updated_at=str(value["updated_at"]),
            closed_at=_optional_string(value.get("closed_at")),
            merged_at=_optional_string(value.get("merged_at")),
            additions=int(value["additions"]),
            deletions=int(value["deletions"]),
            changed_files=int(value["changed_files"]),
            labels=tuple(str(label) for label in value.get("labels", [])),
        )


@dataclass(frozen=True, slots=True)
class PullRequestNote:
    """Optional user-maintained metadata for a pull request."""

    category: str = ""
    note: str = ""
    highlight: bool = False

    @classmethod
    def from_value(cls, value: Any) -> PullRequestNote:
        """Parse a mapping or a shorthand note string."""

        if isinstance(value, str):
            return cls(note=value.strip())
        if value is None:
            return cls()
        if not isinstance(value, dict):
            raise ValueError("A PR note must be a mapping, string, or null")
        return cls(
            category=str(value.get("category", "")).strip(),
            note=str(value.get("note", "")).strip(),
            highlight=bool(value.get("highlight", False)),
        )


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
