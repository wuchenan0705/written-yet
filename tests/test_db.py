import sqlite3

from sqlalchemy import create_engine, inspect

from app import db


def test_old_database_gets_new_columns(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE submission (id INTEGER PRIMARY KEY, created_at DATETIME, date VARCHAR, "
                "skill VARCHAR, source VARCHAR, raw_text VARCHAR, question_count INTEGER, "
                "correct_count INTEGER, result JSON)")
    con.execute("INSERT INTO submission VALUES (1, '2026-10-20 10:00:00', '2026-10-20', 'reading', "
                "'web', '', 3, 2, '{}')")
    con.commit()
    con.close()
    monkeypatch.setattr(db, "engine", create_engine(f"sqlite:///{path}"))
    db.init_db()
    cols = {c["name"] for c in inspect(db.engine).get_columns("submission")}
    assert {"book", "test", "part", "title"} <= cols
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT book, part FROM submission").fetchone() == ("", "")
    db.init_db()  # second run is a no-op
