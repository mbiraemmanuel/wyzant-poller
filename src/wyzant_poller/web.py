import functools
import json
import os
import sqlite3
import subprocess
import time
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request, send_from_directory

load_dotenv()

_HERE = Path(__file__).parent
app = Flask(__name__, static_folder=str(_HERE / "static"))

_WEB_USER = os.getenv("WEB_USER", "admin")
_WEB_PASSWORD = os.getenv("WEB_PASSWORD", "changeme")
_STATE_DIR = Path(os.getenv("STATE_DIR", ".state"))
_DB_PATH = _STATE_DIR / "jobs.db"
_LOG_PATH = _STATE_DIR / "poller.log"


def _requires_auth(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or auth.username != _WEB_USER or auth.password != _WEB_PASSWORD:
            return Response(
                "Unauthorized", 401,
                {"WWW-Authenticate": 'Basic realm="Wyzant Poller"'},
            )
        return f(*args, **kwargs)
    return decorated


def _migrate():
    if not _DB_PATH.exists():
        return
    with sqlite3.connect(_DB_PATH) as conn:
        for col_sql in [
            "ALTER TABLE job_history ADD COLUMN status TEXT DEFAULT 'new'",
            "ALTER TABLE job_history ADD COLUMN note TEXT DEFAULT ''",
        ]:
            try:
                conn.execute(col_sql)
            except sqlite3.OperationalError:
                pass
        conn.execute("CREATE TABLE IF NOT EXISTS subjects (name TEXT PRIMARY KEY)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS health_events (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                at        REAL NOT NULL,
                ok        INTEGER NOT NULL,
                job_count INTEGER,
                message   TEXT
            )
        """)


@app.get("/")
@_requires_auth
def index():
    return send_from_directory(app.static_folder, "dashboard.html")


@app.get("/support.js")
@_requires_auth
def support_js():
    return send_from_directory(app.static_folder, "support.js")


@app.get("/api/status")
@_requires_auth
def api_status():
    try:
        r = subprocess.run(
            ["systemctl", "is-active", "wyzant-poller"],
            capture_output=True, text=True,
        )
        status = r.stdout.strip()
    except FileNotFoundError:
        status = "unknown"  # systemctl not available (non-Linux)
    last_poll = None
    if _DB_PATH.exists():
        with sqlite3.connect(_DB_PATH) as conn:
            row = conn.execute(
                "SELECT value FROM metadata WHERE key='last_poll_at'"
            ).fetchone()
            if row:
                try:
                    last_poll = float(row[0])
                except (ValueError, TypeError):
                    pass
    return jsonify(status=status, last_poll_at=last_poll)


@app.get("/api/jobs")
@_requires_auth
def api_jobs():
    _migrate()
    if not _DB_PATH.exists():
        return jsonify(jobs=[])
    with sqlite3.connect(_DB_PATH) as conn:
        rows = conn.execute(
            "SELECT id, title, subject, url, first_seen, status, note "
            "FROM job_history ORDER BY first_seen DESC"
        ).fetchall()
    jobs = [
        {
            "id": r[0],
            "title": r[1],
            "subject": r[2] or "General",
            "url": r[3],
            "first_seen": r[4],
            "status": r[5] or "new",
            "note": r[6] or "",
        }
        for r in rows
    ]
    return jsonify(jobs=jobs)


@app.patch("/api/jobs/<job_id>")
@_requires_auth
def api_update_job(job_id):
    data = request.get_json(force=True, silent=True) or {}
    _migrate()
    with sqlite3.connect(_DB_PATH) as conn:
        if "status" in data:
            conn.execute(
                "UPDATE job_history SET status=? WHERE id=?",
                (data["status"], job_id),
            )
        if "note" in data:
            conn.execute(
                "UPDATE job_history SET note=? WHERE id=?",
                (data["note"], job_id),
            )
    return jsonify(ok=True)


@app.post("/api/poller/<action>")
@_requires_auth
def api_poller(action):
    if action not in ("start", "stop", "restart"):
        return jsonify(error="invalid action"), 400
    try:
        r = subprocess.run(
            ["sudo", "systemctl", action, "wyzant-poller"],
            capture_output=True, text=True,
        )
        return jsonify(ok=r.returncode == 0)
    except FileNotFoundError:
        return jsonify(ok=False, error="systemctl not available")


@app.get("/api/logs/stream")
@_requires_auth
def api_logs_stream():
    def generate():
        if _LOG_PATH.exists():
            lines = _LOG_PATH.read_text(errors="replace").splitlines()
            for line in lines[-50:]:
                yield f"data: {json.dumps(line)}\n\n"
        if not _LOG_PATH.exists():
            while True:
                yield "data: null\n\n"
                time.sleep(2)
        with open(_LOG_PATH, errors="replace") as f:
            f.seek(0, 2)
            while True:
                line = f.readline()
                if line:
                    yield f"data: {json.dumps(line.rstrip())}\n\n"
                else:
                    yield "data: null\n\n"
                    time.sleep(1)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/health-events")
@_requires_auth
def api_health_events():
    _migrate()
    if not _DB_PATH.exists():
        return jsonify(events=[])
    with sqlite3.connect(_DB_PATH) as conn:
        rows = conn.execute(
            "SELECT at, ok, job_count, message FROM health_events ORDER BY at DESC LIMIT 100"
        ).fetchall()
    events = [
        {"at": r[0], "ok": bool(r[1]), "job_count": r[2], "message": r[3]}
        for r in rows
    ]
    return jsonify(events=events)


@app.get("/api/analytics")
@_requires_auth
def api_analytics():
    _migrate()
    if not _DB_PATH.exists():
        return jsonify(hourly=[], subjects=[], total=0, from_ts=None, to_ts=None)
    with sqlite3.connect(_DB_PATH) as conn:
        hourly = conn.execute(
            "SELECT CAST((first_seen - 4*3600) % 86400 / 3600 AS INT) as hr, COUNT(*) cnt "
            "FROM job_history GROUP BY hr ORDER BY hr"
        ).fetchall()
        subjects = conn.execute(
            "SELECT COALESCE(subject,'General'), COUNT(*) cnt FROM job_history "
            "GROUP BY subject ORDER BY cnt DESC LIMIT 10"
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM job_history").fetchone()[0]
        dr = conn.execute("SELECT MIN(first_seen), MAX(first_seen) FROM job_history").fetchone()
    return jsonify(
        hourly=[{"hour": r[0], "count": r[1]} for r in hourly],
        subjects=[{"subject": r[0], "count": r[1]} for r in subjects],
        total=total, from_ts=dr[0], to_ts=dr[1],
    )


@app.get("/api/subjects")
@_requires_auth
def api_subjects():
    _migrate()
    if not _DB_PATH.exists():
        return jsonify(subjects=[])
    with sqlite3.connect(_DB_PATH) as conn:
        rows = conn.execute("SELECT name FROM subjects ORDER BY name").fetchall()
    return jsonify(subjects=[r[0] for r in rows])


@app.post("/api/subjects")
@_requires_auth
def api_add_subject():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify(error="name required"), 400
    _migrate()
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute("INSERT OR IGNORE INTO subjects (name) VALUES (?)", (name,))
    return jsonify(ok=True)


@app.delete("/api/subjects/<name>")
@_requires_auth
def api_remove_subject(name):
    _migrate()
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute("DELETE FROM subjects WHERE name=?", (name,))
    return jsonify(ok=True)


def main():
    _migrate()
    port = int(os.getenv("WEB_PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
