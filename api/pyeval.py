"""pyeval: score model-written Python answers against test cases and log reproducible failures.

Usage: python pyeval.py tasks.json answers.json [-o report.json]
Each task has an id, entrypoint, and tests [{"args": [...], "expected": ...}].
Each answer is {"task_id": ..., "code": "..."}; code runs in a subprocess with a timeout.
"""
import argparse, json, subprocess, sys, tempfile, textwrap, os, ast

RUNNER = textwrap.dedent('''
    import json, sys, traceback
    ns = {}
    try:
        exec(compile(open(sys.argv[1]).read(), "answer", "exec"), ns)
        fn = ns[sys.argv[2]]
        out = fn(*json.loads(sys.argv[3]))
        print(json.dumps({"ok": True, "value": out}))
    except BaseException:
        print(json.dumps({"ok": False, "trace": traceback.format_exc()}))
''')

def classify(res, expected):
    if res.get("timeout"):
        return "timeout"
    if not res["ok"]:
        t = res["trace"]
        for name in ("SyntaxError", "NameError", "KeyError", "IndexError", "TypeError", "RecursionError"):
            if name in t:
                return name
        return "exception"
    return "pass" if res["value"] == expected else "wrong_answer"

def run_case(code, entry, args, timeout=3):
    with tempfile.TemporaryDirectory() as d:
        a, r = os.path.join(d, "a.py"), os.path.join(d, "r.py")
        open(a, "w").write(code); open(r, "w").write(RUNNER)
        try:
            p = subprocess.run([sys.executable, r, a, entry, json.dumps(args)],
                               capture_output=True, text=True, timeout=timeout)
            return json.loads(p.stdout.strip().splitlines()[-1])
        except subprocess.TimeoutExpired:
            return {"ok": False, "timeout": True}
        except Exception as e:
            return {"ok": False, "trace": f"runner failure: {e}"}

def quality_flags(code):
    flags = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return ["does_not_parse"]
    if not ast.get_docstring(tree) and not any(ast.get_docstring(n) for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        flags.append("no_docstring")
    if any(isinstance(n, ast.ExceptHandler) and n.type is None for n in ast.walk(tree)):
        flags.append("bare_except")
    return flags

def evaluate(tasks, answers):
    by_id = {t["id"]: t for t in tasks}
    report = []
    for ans in answers:
        t = by_id[ans["task_id"]]
        cases = []
        for c in t["tests"]:
            res = run_case(ans["code"], t["entrypoint"], c["args"])
            cases.append({"args": c["args"], "expected": c["expected"], "verdict": classify(res, c["expected"]),
                          "got": res.get("value"), "trace": res.get("trace")})
        passed = sum(c["verdict"] == "pass" for c in cases)
        report.append({"task_id": t["id"], "passed": passed, "total": len(cases),
                       "failure_modes": sorted({c["verdict"] for c in cases if c["verdict"] != "pass"}),
                       "quality_flags": quality_flags(ans["code"]), "cases": cases})
    return report

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tasks"); ap.add_argument("answers"); ap.add_argument("-o")
    a = ap.parse_args()
    rep = evaluate(json.load(open(a.tasks)), json.load(open(a.answers)))
    for r in rep:
        print(f'{r["task_id"]}: {r["passed"]}/{r["total"]} modes={r["failure_modes"]} flags={r["quality_flags"]}')
    if a.o: json.dump(rep, open(a.o, "w"), indent=2)

if __name__ == "__main__":
    main()
