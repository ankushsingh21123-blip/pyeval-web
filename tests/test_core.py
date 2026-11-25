import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import pytest
import core

def test_lint_parses_and_flags():
    r = core.lint("def f():\n    try:\n        pass\n    except:\n        pass\n")
    assert r["parses"] and "bare_except" in r["flags"]

def test_lint_syntax_error():
    assert core.lint("def f(")["parses"] is False

def test_lint_rejects_oversize():
    assert core.lint("x=1\n" * 5000)["flags"] == ["invalid_or_too_long"]

def test_lint_never_executes(tmp_path):
    marker = tmp_path / "pwned"
    core.lint(f"import os\nopen({str(marker)!r}, 'w').write('x')\n")
    assert not marker.exists()

DB = os.environ.get("DATABASE_URL")
pg = pytest.mark.skipif(not DB, reason="needs Postgres (DATABASE_URL)")

@pytest.fixture
def conn():
    import psycopg2
    c = psycopg2.connect(DB)
    with c.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS runs, answers, tasks CASCADE")
    c.commit()
    core.init_db(c)
    yield c
    c.close()

@pg
def test_tasks_listed(conn):
    st, out = core.handle(conn, "GET", "/api/tasks", {})
    assert st == 200 and {t["id"] for t in out} == {"fib", "rev"}

@pg
def test_run_persists_and_lists(conn):
    _, tasks = core.handle(conn, "GET", "/api/tasks", {})
    good = next(a for t in tasks if t["id"] == "fib" for a in t["answers"] if a["label"] == "correct iterative")
    bad = next(a for t in tasks if t["id"] == "fib" for a in t["answers"] if a["label"] == "off by one")
    st, r = core.handle(conn, "POST", "/api/runs", {"answer_id": good["id"]})
    assert st == 201 and r["passed"] == r["total"] == 3
    st, r = core.handle(conn, "POST", "/api/runs", {"answer_id": bad["id"]})
    assert r["failure_modes"] == ["wrong_answer"]
    st, runs = core.handle(conn, "GET", "/api/runs", {})
    assert len(runs) == 2 and runs[0]["label"] == "off by one"

@pg
def test_crash_answer_has_error_mode(conn):
    _, tasks = core.handle(conn, "GET", "/api/tasks", {})
    a = next(a for t in tasks if t["id"] == "rev" for a in t["answers"] if a["label"] == "crashes on empty")
    _, r = core.handle(conn, "POST", "/api/runs", {"answer_id": a["id"]})
    assert "IndexError" in r["failure_modes"]

@pg
def test_run_rejects_client_code_and_bad_ids(conn):
    assert core.handle(conn, "POST", "/api/runs", {"code": "print(1)"})[0] == 400
    assert core.handle(conn, "POST", "/api/runs", {"answer_id": 99999})[0] == 404
    assert core.handle(conn, "GET", "/api/nope", {})[0] == 404
