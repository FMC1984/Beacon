"""Admin DB restore: swap in an uploaded SQLite database (one-time migration
helper, e.g. copying a local Beacon up to the hosted instance). Validates the
upload, backs up the current file, and reindexes."""

import sqlite3

import pytest

from app.config import settings


def _make_beacon_db(path, prop_name="Imported Prop"):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE alembic_version (version_num TEXT)")
    conn.execute("INSERT INTO alembic_version VALUES ('d0e1f2a3b4c5')")
    conn.execute("CREATE TABLE properties (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO properties (name) VALUES (?)", (prop_name,))
    conn.commit()
    conn.close()


@pytest.fixture()
def sqlite_instance(tmp_path, monkeypatch):
    live = tmp_path / "beacon.db"
    _make_beacon_db(live, "Original")
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{live}")
    # Point the admin module's engine + build_index at the temp DB.
    from sqlalchemy import create_engine
    import app.routers.admin as admin

    test_engine = create_engine(f"sqlite:///{live}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(admin, "engine", test_engine)
    monkeypatch.setattr(admin, "build_index", lambda db, emb: {"chunks_total": 0, "embedded": 0})
    monkeypatch.setattr(admin, "get_embedder", lambda: object())
    return live


def test_restore_swaps_in_uploaded_db(client, sqlite_instance, tmp_path):
    incoming = tmp_path / "upload.db"
    _make_beacon_db(incoming, "Restored From Laptop")

    r = client.post(
        "/api/admin/restore-db",
        files={"file": ("beacon.db", incoming.read_bytes(), "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["properties_restored"] == 1
    assert body["backup"] is not None  # previous DB was backed up

    # The live file now holds the uploaded property, and a backup exists.
    live = sqlite3.connect(sqlite_instance)
    assert live.execute("SELECT name FROM properties").fetchone()[0] == "Restored From Laptop"
    live.close()
    assert list(sqlite_instance.parent.glob("beacon.backup-*.db"))


def test_restore_rejects_non_beacon_file(client, sqlite_instance, tmp_path):
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"this is not a database")
    r = client.post(
        "/api/admin/restore-db",
        files={"file": ("beacon.db", junk.read_bytes(), "application/octet-stream")},
    )
    assert r.status_code == 422
    # The live DB is untouched.
    live = sqlite3.connect(sqlite_instance)
    assert live.execute("SELECT name FROM properties").fetchone()[0] == "Original"
    live.close()


def test_restore_rejects_wrong_schema(client, sqlite_instance, tmp_path):
    wrong = tmp_path / "wrong.db"
    conn = sqlite3.connect(wrong)
    conn.execute("CREATE TABLE something_else (id INTEGER)")
    conn.commit()
    conn.close()
    r = client.post(
        "/api/admin/restore-db",
        files={"file": ("beacon.db", wrong.read_bytes(), "application/octet-stream")},
    )
    assert r.status_code == 422
