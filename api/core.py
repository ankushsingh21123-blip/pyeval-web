"""Request logic for pyeval-web. No arbitrary client code is ever executed:
runs only use answers stored in the database (our own fixed fixtures);
client-submitted code is only parsed with ast (static lint), never run."""
import ast, json
import pyeval

SEED_TASKS = [
    {"id": "fib", "title": "Fibonacci", "entrypoint": "fib",
     "tests": [{"args": [10], "expected": 55}, {"args": [0], "expected": 0}, {"args": [1], "expected": 1}]},
    {"id": "rev", "title": "Reverse a string", "entrypoint": "rev",
     "tests": [{"args": ["abc"], "expected": "cba"}, {"args": [""], "expected": ""}]},
]
SEED_ANSWERS = [
    ("fib", "correct iterative", "def fib(n):\n    \"\"\"Iterative fibonacci.\"\"\"\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a\n"),
    ("fib", "off by one", "def fib(n):\n    a, b = 1, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a\n"),
    ("rev", "correct slice", "def rev(s):\n    \"\"\"Reverse.\"\"\"\n    return s[::-1]\n"),
    ("rev", "crashes on empty", "def rev(s):\n    return s[0] + s[-1]\n"),
    ("rev", "swallows errors", "def rev(s):\n    try:\n        return s[::-1]\n    except:\n        return ''\n"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks(id text PRIMARY KEY, title text NOT NULL, entrypoint text NOT NULL, tests jsonb NOT NULL);
CREATE TABLE IF NOT EXISTS answers(id serial PRIMARY KEY, task_id text NOT NULL REFERENCES tasks(id), label text NOT NULL, code text NOT NULL, UNIQUE(task_id,label));
CREATE TABLE IF NOT EXISTS runs(id serial PRIMARY KEY, answer_id int NOT NULL REFERENCES answers(id), passed int NOT NULL, total int NOT NULL, failure_modes jsonb NOT NULL, quality_flags jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
"""

def init_db(conn):
    with conn.cursor() as c:
        c.execute(SCHEMA)
        for t in SEED_TASKS:
            c.execute("INSERT INTO tasks VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                      (t["id"], t["title"], t["entrypoint"], json.dumps(t["tests"])))
        for tid, label, code in SEED_ANSWERS:
            c.execute("INSERT INTO answers(task_id,label,code) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING", (tid, label, code))
    conn.commit()

def lint(code):
    """Static analysis only. Returns parse status and quality flags."""
    if not isinstance(code, str) or len(code) > 5000:
        return {"parses": False, "flags": ["invalid_or_too_long"]}
    try:
        ast.parse(code)
    except SyntaxError as e:
        return {"parses": False, "flags": ["does_not_parse"], "error": f"line {e.lineno}: {e.msg}"}
    return {"parses": True, "flags": pyeval.quality_flags(code)}

def handle(conn, method, path, body):
    """Returns (status, json-able)."""
    with conn.cursor() as c:
        if method == "GET" and path == "/api/health":
            c.execute("SELECT 1"); return 200, {"ok": True}
        if method == "GET" and path == "/api/tasks":
            c.execute("SELECT t.id,t.title,a.id,a.label FROM tasks t JOIN answers a ON a.task_id=t.id ORDER BY t.id,a.id")
            out = {}
            for tid, title, aid, label in c.fetchall():
                out.setdefault(tid, {"id": tid, "title": title, "answers": []})["answers"].append({"id": aid, "label": label})
            return 200, list(out.values())
        if method == "GET" and path == "/api/runs":
            c.execute("SELECT r.id,a.task_id,a.label,r.passed,r.total,r.failure_modes,r.quality_flags,r.created_at FROM runs r JOIN answers a ON a.id=r.answer_id ORDER BY r.id DESC LIMIT 50")
            return 200, [dict(id=r[0], task_id=r[1], label=r[2], passed=r[3], total=r[4], failure_modes=r[5], quality_flags=r[6], created_at=r[7].isoformat()) for r in c.fetchall()]
        if method == "POST" and path == "/api/runs":
            aid = body.get("answer_id")
            if not isinstance(aid, int):
                return 400, {"error": "answer_id (int) required"}
            c.execute("SELECT a.code,t.id,t.entrypoint,t.tests FROM answers a JOIN tasks t ON t.id=a.task_id WHERE a.id=%s", (aid,))
            row = c.fetchone()
            if not row:
                return 404, {"error": "unknown answer_id"}
            code, tid, entry, tests = row
            rep = pyeval.evaluate([{"id": tid, "entrypoint": entry, "tests": tests}], [{"task_id": tid, "code": code}])[0]
            c.execute("INSERT INTO runs(answer_id,passed,total,failure_modes,quality_flags) VALUES(%s,%s,%s,%s,%s) RETURNING id",
                      (aid, rep["passed"], rep["total"], json.dumps(rep["failure_modes"]), json.dumps(rep["quality_flags"])))
            rid = c.fetchone()[0]
            conn.commit()
            return 201, {"id": rid, "passed": rep["passed"], "total": rep["total"],
                         "failure_modes": rep["failure_modes"], "quality_flags": rep["quality_flags"]}
    if method == "POST" and path == "/api/lint":
        return 200, lint(body.get("code"))
    return 404, {"error": "not found"}
