from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from collector.deploy import (
    DeployConfigError,
    DeploySettings,
    extract_deploy_token,
    request_deploy_restart,
    token_is_valid,
)


def test_extract_deploy_token_from_bearer():
    token = extract_deploy_token({"Authorization": "Bearer secret-token"}, {})
    assert token == "secret-token"


def test_token_is_valid(tmp_path, monkeypatch):
    cfg = tmp_path / "deploy.json"
    cfg.write_text(json.dumps({"token": "abc123"}), encoding="utf-8")
    settings = DeploySettings.load(cfg)
    assert token_is_valid("abc123", settings)
    assert not token_is_valid("wrong", settings)


def test_missing_token_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("DEPLOY_TOKEN", raising=False)
    with pytest.raises(DeployConfigError):
        DeploySettings.load(tmp_path / "missing.json")


def test_request_deploy_restart(tmp_path, monkeypatch):
    cfg = tmp_path / "deploy.json"
    cfg.write_text(json.dumps({"token": "secret"}), encoding="utf-8")
    settings = DeploySettings(token="secret", branch="main", port=8787)

    with patch("collector.deploy.DeploySettings.load", return_value=settings), patch(
        "collector.deploy.spawn_restart_worker", return_value=tmp_path / "deploy.log"
    ) as spawn, patch("notify.shutdown.request_shutdown", return_value=True) as shutdown:
        result = request_deploy_restart()

    assert result["ok"] is True
    spawn.assert_called_once()
    shutdown.assert_called_once()
