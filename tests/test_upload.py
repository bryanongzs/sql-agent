import pytest

from db import QueryError, run_query
from schema_tools import describe_schema, load_uploads


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def test_csvs_load_and_are_described(tmp_path):
    a = write(tmp_path / "My Orders.csv", "Order ID,Customer Id,Total $\n1,10,5.5\n2,11,7\n")
    b = write(tmp_path / "customers.csv", "customer_id,name\n10,Ann\n11,Bob\n")
    db_path, report = load_uploads([a, b], tmp_path / "out")
    assert run_query("SELECT COUNT(*) FROM my_orders", db_path=db_path)["rows"] == [(2,)]
    cols = [r[0] for r in run_query("SELECT name FROM pragma_table_info('my_orders')",
                                    db_path=db_path)["rows"]]
    assert cols == ["order_id", "customer_id", "total"]
    schema = describe_schema(db_path)
    assert "TABLE customers" in schema and "customer_id: customers, my_orders" in schema


def test_duplicate_column_names_are_made_unique(tmp_path):
    f = write(tmp_path / "t.csv", "a,a,A\n1,2,3\n")
    db_path, _ = load_uploads([f], tmp_path / "out")
    cols = [r[0] for r in run_query("SELECT name FROM pragma_table_info('t')",
                                    db_path=db_path)["rows"]]
    assert cols == ["a", "a_1", "a_2"]

def test_uploaded_db_is_read_only(tmp_path):
    f = write(tmp_path / "t.csv", "x\n1\n2\n")
    db_path, _ = load_uploads([f], tmp_path / "out")
    with pytest.raises(QueryError):
        run_query("DELETE FROM t", db_path=db_path)
    assert run_query("SELECT COUNT(*) FROM t", db_path=db_path)["rows"] == [(2,)]


def test_too_many_files(tmp_path):
    files = [write(tmp_path / f"f{i}.csv", "x\n1\n") for i in range(11)]
    with pytest.raises(ValueError, match="Too many"):
        load_uploads(files, tmp_path / "out")


def test_unsupported_file_type(tmp_path):
    f = write(tmp_path / "notes.txt", "hello")
    with pytest.raises(ValueError, match="Unsupported"):
        load_uploads([f], tmp_path / "out")


def test_header_only_csv_gives_no_tables(tmp_path):
    f = write(tmp_path / "empty.csv", "a,b\n")
    with pytest.raises(ValueError, match="No usable"):
        load_uploads([f], tmp_path / "out")


def test_single_sqlite_file_is_copied(tmp_path):
    import sqlite3
    src = tmp_path / "mine.db"
    conn = sqlite3.connect(src)
    conn.execute("CREATE TABLE pets (id INTEGER, name TEXT)")
    conn.execute("INSERT INTO pets VALUES (1, 'Rex')")
    conn.commit()
    conn.close()
    db_path, _ = load_uploads([src], tmp_path / "out")
    assert run_query("SELECT name FROM pets", db_path=db_path)["rows"] == [("Rex",)]