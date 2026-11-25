import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from http.server import BaseHTTPRequestHandler
import psycopg2
import core

_ready = False

def connect():
    global _ready
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    if not _ready:
        core.init_db(conn); _ready = True
    return conn

class handler(BaseHTTPRequestHandler):
    def _go(self, method):
        try:
            n = int(self.headers.get("content-length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}") if n <= 20000 else {}
            if not isinstance(body, dict): body = {}
            conn = connect()
            try:
                status, out = core.handle(conn, method, self.path.split("?")[0], body)
            finally:
                conn.close()
        except Exception:
            status, out = 500, {"error": "server error"}
        data = json.dumps(out).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers(); self.wfile.write(data)
    def do_GET(self): self._go("GET")
    def do_POST(self): self._go("POST")
