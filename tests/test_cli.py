from pathlib import Path

import pr_record.cli as cli_module
from pr_record.cli import main
from pr_record.config import AppConfig
from pr_record.sync import SyncSummary


def _write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
github:
  username: WhatGhost
  excluded_repositories: []
files:
  data: data/prs.json
  notes: notes.yml
  readme: README.md
""".lstrip(),
        encoding="utf-8",
    )
    return config_path


def test_render_command_creates_readme(tmp_path: Path, capsys) -> None:
    config_path = _write_config(tmp_path)

    exit_code = main(["--config", str(config_path), "render"])

    assert exit_code == 0
    assert (tmp_path / "README.md").exists()
    assert "README updated" in capsys.readouterr().out


def test_sync_command_requires_token(tmp_path: Path, monkeypatch, capsys) -> None:
    config_path = _write_config(tmp_path)
    monkeypatch.delenv("PR_READ_TOKEN", raising=False)

    exit_code = main(["--config", str(config_path), "sync"])

    assert exit_code == 1
    assert "PR_READ_TOKEN is required" in capsys.readouterr().err


def test_sync_command_reports_results(tmp_path: Path, monkeypatch, capsys) -> None:
    config_path = _write_config(tmp_path)
    monkeypatch.setenv("PR_READ_TOKEN", "read-token")

    def fake_sync(config: AppConfig, token: str) -> SyncSummary:
        assert config.github_username == "WhatGhost"
        assert token == "read-token"
        return SyncSummary(total=8, fetched=10, filtered=2, changed=True)

    def fake_render(config: AppConfig) -> bool:
        assert config.github_username == "WhatGhost"
        return True

    monkeypatch.setattr(cli_module, "sync_from_github", fake_sync)
    monkeypatch.setattr(cli_module, "render_from_files", fake_render)

    exit_code = main(["--config", str(config_path), "sync"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Synchronized 10 PRs; retained 8; filtered 2" in output
    assert "Generated files updated" in output
