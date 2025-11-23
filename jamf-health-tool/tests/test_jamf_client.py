import types

import pytest

from jamf_health_tool.jamf_client import JamfApiError, JamfCliError, jamf_api_call


def test_jamf_api_call_success(monkeypatch):
    def fake_run(cmd, capture_output, text, check):
        return types.SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    resp = jamf_api_call("/api/test")
    assert resp["ok"] is True


def test_jamf_api_call_nonzero(monkeypatch):
    def fake_run(cmd, capture_output, text, check):
        return types.SimpleNamespace(returncode=1, stdout="bad", stderr="err")

    monkeypatch.setattr("subprocess.run", fake_run)
    with pytest.raises(JamfCliError):
        jamf_api_call("/api/test")


def test_jamf_api_call_bad_json(monkeypatch):
    def fake_run(cmd, capture_output, text, check):
        return types.SimpleNamespace(returncode=0, stdout="not-json", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    with pytest.raises(JamfApiError):
        jamf_api_call("/api/test")
