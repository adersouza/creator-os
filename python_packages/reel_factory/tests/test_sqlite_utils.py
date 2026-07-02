import threading
from pathlib import Path

import sqlite_utils as sqlite_utils_shim
from reel_factory import sqlite_utils as packaged_sqlite_utils
from reel_factory.sqlite_utils import connect_sqlite


def test_production_sqlite_connects_use_shared_helper() -> None:
    package_root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for path in sorted(package_root.rglob("*.py")):
        relative = path.relative_to(package_root)
        if relative.parts[0] == "tests":
            continue
        if path.name == "sqlite_utils.py":
            continue
        if "sqlite3.connect(" in path.read_text(encoding="utf-8"):
            offenders.append(str(relative))

    assert offenders == []


def test_top_level_sqlite_utils_shim_reexports_packaged_helper() -> None:
    assert sqlite_utils_shim.connect_sqlite is packaged_sqlite_utils.connect_sqlite
    assert connect_sqlite is packaged_sqlite_utils.connect_sqlite


def test_connect_sqlite_sets_busy_timeout_and_wal(tmp_path: Path) -> None:
    conn = connect_sqlite(tmp_path / "manifest.sqlite")
    try:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30_000
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        conn.close()


def test_connect_sqlite_reader_writer_smoke(tmp_path: Path) -> None:
    db = tmp_path / "manifest.sqlite"
    conn = connect_sqlite(db)
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    writer_ready = threading.Event()
    release_writer = threading.Event()
    errors: list[BaseException] = []
    counts: list[int] = []

    def writer() -> None:
        try:
            write_conn = connect_sqlite(db)
            write_conn.execute("BEGIN IMMEDIATE")
            write_conn.execute("INSERT INTO items (id) VALUES (1)")
            writer_ready.set()
            release_writer.wait(timeout=2)
            write_conn.commit()
            write_conn.close()
        except BaseException as exc:  # pragma: no cover - surfaced after join
            errors.append(exc)

    def reader() -> None:
        try:
            writer_ready.wait(timeout=2)
            read_conn = connect_sqlite(db, readonly=True, wal=False)
            counts.append(read_conn.execute("SELECT COUNT(*) FROM items").fetchone()[0])
            read_conn.close()
        except BaseException as exc:  # pragma: no cover - surfaced after join
            errors.append(exc)
        finally:
            release_writer.set()

    writer_thread = threading.Thread(target=writer)
    reader_thread = threading.Thread(target=reader)
    writer_thread.start()
    reader_thread.start()
    writer_thread.join(timeout=3)
    reader_thread.join(timeout=3)

    assert errors == []
    assert counts == [0]
    final_conn = connect_sqlite(db)
    try:
        assert final_conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1
    finally:
        final_conn.close()
