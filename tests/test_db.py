import sqlite3

import pytest

import db
from db import QueryError, run_query


@pytest.fixture
def small_db(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (id INTEGER, name TEXT)")
    conn.executemany("INSERT INTO t VALUES (?, ?)", [(i, f"n{i}") for i in range(300)])
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


def test_select_works(small_db):
    res = run_query("SELECT COUNT(*) FROM t")
    assert res["rows"] == [(300,)]


def test_trailing_semicolon_ok(small_db):
    assert run_query("SELECT 1;")["rows"] == [(1,)]


@pytest.mark.parametrize("sql", [
    "DROP TABLE t",
    "DELETE FROM t",
    "UPDATE t SET name = 'x'",
    "INSERT INTO t VALUES (1, 'a')",
])
def test_non_select_rejected(small_db, sql):
    with pytest.raises(QueryError):
        run_query(sql)


def test_multiple_statements_rejected(small_db):
    with pytest.raises(QueryError):
        run_query("SELECT 1; DELETE FROM t")


def test_write_hidden_behind_with_is_blocked_by_read_only(small_db):
    with pytest.raises(QueryError):
        run_query("WITH x AS (SELECT 1) DELETE FROM t")
    conn = sqlite3.connect(small_db)
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 300
    conn.close()


def test_row_cap(small_db):
    res = run_query("SELECT * FROM t")
    assert len(res["rows"]) == db.MAX_ROWS
    assert res["truncated"] is True


def test_small_result_not_truncated(small_db):
    assert run_query("SELECT * FROM t WHERE id < 5")["truncated"] is False


def test_unknown_table_raises_query_error(small_db):
    with pytest.raises(QueryError):
        run_query("SELECT * FROM nope")


def test_timeout(small_db):
    slow = ("WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c "
            "WHERE x < 100000000) SELECT COUNT(*) FROM c")
    with pytest.raises(QueryError, match="time limit"):
        run_query(slow, timeout=0.3)