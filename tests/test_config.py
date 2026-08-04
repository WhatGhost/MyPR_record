from pathlib import Path

import pytest

from pr_record.config import AppConfig, ConfigError, load_config


def _config(*patterns: str) -> AppConfig:
    return AppConfig(
        github_username="WhatGhost",
        include_private=False,
        excluded_repositories=patterns,
        data_file=Path("data/prs.json"),
        notes_file=Path("notes.yml"),
        readme_file=Path("README.md"),
    )


def test_repository_exclusion_supports_exact_case_insensitive_matches() -> None:
    config = _config("WhatGhost/MyPR_record")

    assert config.is_repository_excluded("whatghost/mypr_RECORD")
    assert not config.is_repository_excluded("WhatGhost/another-repo")


def test_repository_exclusion_supports_shell_wildcards() -> None:
    config = _config("private-labs/*", "*/scratch-*")

    assert config.is_repository_excluded("private-labs/demo")
    assert config.is_repository_excluded("octocat/scratch-test")
    assert not config.is_repository_excluded("octocat/production")


def test_load_config_resolves_relative_paths(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
github:
  username: WhatGhost
  excluded_repositories:
    - WhatGhost/MyPR_record
files:
  data: data/prs.json
  notes: notes.yml
  readme: README.md
""".lstrip(),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.github_username == "WhatGhost"
    assert config.data_file == tmp_path / "data/prs.json"
    assert config.is_repository_excluded("WhatGhost/MyPR_record")


def test_load_config_rejects_non_list_exclusions(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
github:
  username: WhatGhost
  excluded_repositories: WhatGhost/MyPR_record
files:
  data: data/prs.json
  notes: notes.yml
  readme: README.md
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="must be a list"):
        load_config(config_path)


def test_load_config_reports_missing_and_invalid_yaml(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yml"
    with pytest.raises(ConfigError, match="does not exist"):
        load_config(missing)

    invalid = tmp_path / "invalid.yml"
    invalid.write_text("github: [unterminated", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_config(invalid)
