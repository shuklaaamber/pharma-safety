#!/usr/bin/env python3
"""PostToolUse hook: record file-edit events to a local audit log.

Reads the hook payload from stdin and appends ONE JSON line containing only:
    ts_utc, tool_name, file_path
It deliberately never reads or stores tool_input content (edit text, file
bodies, descriptions) so no sensitive data can reach the log.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parents[2] / "logs" / "edit_audit.jsonl"


def build_record(payload: dict) -> dict:
    tool_input = payload.get("tool_input")
    file_path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    return {
        "ts_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool_name": str(payload.get("tool_name", "unknown")),
        "file_path": str(file_path) if file_path else None,
    }


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("payload is not a JSON object")
        record = build_record(payload)
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception as exc:  # never block the tool call; report on stderr
        print(f"audit_edit hook error: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
