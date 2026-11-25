from pathlib import Path

from streamlit.testing.v1 import AppTest

from pharma_intake import config

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _run(tmp_path, monkeypatch, query):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "a.db")
    at = AppTest.from_file(APP).run(timeout=30)
    ask = [t for t in at.text_input if t.label.startswith("Ask about")][0]
    ask.set_value(query)
    at.button(key="btn_ask").click().run(timeout=30)
    return at


def test_ask_sop_question_is_extractive_when_toggle_off(tmp_path, monkeypatch):
    at = _run(tmp_path, monkeypatch, "who approves closure of a report?")
    assert not at.exception
    text = " ".join(m.value for m in at.markdown).replace(chr(92), "")  # undo markdown escapes
    assert "[S1]" in text and "SOP-003" in text
    assert any("Extractive" in c.value for c in at.caption)
    assert at.sidebar.toggle[0].value is False  # external LLM is opt-in


def test_ask_no_source(tmp_path, monkeypatch):
    at = _run(tmp_path, monkeypatch, "banana smoothie recipe")
    assert any("No sufficiently relevant source" in m.value.replace(chr(92), "") for m in at.markdown)
