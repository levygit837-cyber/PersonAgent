from __future__ import annotations

import uvicorn
from typer.testing import CliRunner

from personagent.interfaces.cli import main as cli_main


def test_serve_binds_loopback_by_default(monkeypatch):
    runner = CliRunner()
    captured: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs

    monkeypatch.setattr(uvicorn, "run", fake_run)

    result = runner.invoke(cli_main.app, ["serve"])

    assert result.exit_code == 0
    assert captured["kwargs"]["host"] == "127.0.0.1"
