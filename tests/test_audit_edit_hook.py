"""The PostToolUse hook must log only ts_utc / tool_name / file_path, never content."""
import importlib.util
import io
import json
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "audit_edit.py"
SECRET = "PATIENT-FREE-TEXT-SECRET-MARKER"


@pytest.fixture
def hook(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("audit_edit_under_test", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "LOG_PATH", tmp_path / "logs" / "edit_audit.jsonl")
    return mod


def run(hook, monkeypatch, payload):
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    monkeypatch.setattr("sys.stdin", io.StringIO(raw))
    code = hook.main()
    lines = hook.LOG_PATH.read_text(encoding="utf-8").splitlines() if hook.LOG_PATH.exists() else []
    return code, [json.loads(line) for line in lines]


def test_record_has_only_three_keys_and_no_content(hook, monkeypatch):
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "src/example.py",
            "old_string": SECRET,
            "new_string": SECRET,
            "content": SECRET,
        },
        "tool_response": {"output": SECRET},
        "description": SECRET,
    }
    code, records = run(hook, monkeypatch, payload)
    assert code == 0 and len(records) == 1
    assert set(records[0]) == {"ts_utc", "tool_name", "file_path"}
    assert records[0]["tool_name"] == "Edit" and records[0]["file_path"] == "src/example.py"
    assert SECRET not in hook.LOG_PATH.read_text(encoding="utf-8")


def test_missing_tool_input_is_logged_without_path(hook, monkeypatch):
    code, records = run(hook, monkeypatch, {"tool_name": "Write"})
    assert code == 0 and records[0]["file_path"] is None


@pytest.mark.parametrize("bad", ["not json", "[1, 2]", ""])
def test_malformed_payload_never_blocks_and_logs_nothing(hook, monkeypatch, capsys, bad):
    code, records = run(hook, monkeypatch, bad)
    assert code == 0 and records == []
    assert "audit_edit hook error" in capsys.readouterr().err


def test_hook_is_registered_for_edit_tools():
    settings = json.loads((HOOK.parents[1] / "settings.json").read_text(encoding="utf-8"))
    entries = settings["hooks"]["PostToolUse"]
    assert any(
        "Edit" in e["matcher"] and "Write" in e["matcher"]
        and any("audit_edit.py" in h["command"] for h in e["hooks"])
        for e in entries
    )
