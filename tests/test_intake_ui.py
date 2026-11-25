from pathlib import Path

from streamlit.testing.v1 import AppTest

from pharma_intake import config
from pharma_intake.db import Database

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _app(tmp_path, monkeypatch):
    path = tmp_path / "ui.db"
    monkeypatch.setattr(config, "DB_PATH", path)  # form reads config.DB_PATH at call time
    return AppTest.from_file(APP).run(timeout=30), path


def test_empty_submit_lists_errors_and_saves_nothing(tmp_path, monkeypatch):
    at, path = _app(tmp_path, monkeypatch)
    at.button[0].click().run()
    assert at.error and "not saved" in at.error[0].value
    assert not path.exists() or Database(path).list_reports() == []


def test_valid_pqc_submit_saves_and_shows_ref(tmp_path, monkeypatch):
    at, path = _app(tmp_path, monkeypatch)
    at.radio[0].set_value("Product Quality Complaint").run()
    at.text_input[0].set_value("Examplomab")
    at.text_input[1].set_value("LOT-12345")
    at.text_area[0].set_value("Blister packaging was torn.")
    at.button[0].click().run()
    assert not at.exception
    assert "REF-" in at.success[0].value
    assert len(Database(path).list_reports()) == 1
