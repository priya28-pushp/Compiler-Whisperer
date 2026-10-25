"""Accounts, password reset, analysis history and dashboard stats (SQLite)."""
import hashlib, json, os, re, secrets, sqlite3, time
from datetime import datetime, timedelta
from functools import wraps
from flask import Blueprint, g, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

import knowledge

bp = Blueprint("auth", __name__)
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.db")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_fails = {}  # ip -> recent failed login timestamps (simple brute-force guard)


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db


@bp.teardown_app_request
def _close(_):
    d = g.pop("db", None)
    if d:
        d.close()


def init_db():
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE, pw TEXT, created REAL);
    CREATE TABLE IF NOT EXISTS resets(id INTEGER PRIMARY KEY, user_id INTEGER, token TEXT, expires REAL, used INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY, user_id INTEGER, lang TEXT, code TEXT, errors INTEGER,
        warnings INTEGER, ok INTEGER, phases TEXT, titles TEXT, created REAL);
    CREATE TABLE IF NOT EXISTS hints(id INTEGER PRIMARY KEY, user_id INTEGER, title TEXT, level TEXT, created REAL);""")
    c.commit()
    c.close()


def login_required(fn):
    @wraps(fn)
    def wrap(*a, **kw):
        if not session.get("uid"):
            return jsonify(error="Please log in first."), 401
        return fn(*a, **kw)
    return wrap


def password_problem(pw):
    if len(pw) < 8 or not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        return "Password needs at least 8 characters with a letter and a number."


def _hash(t):
    return hashlib.sha256(t.encode()).hexdigest()


@bp.post("/api/signup")
def signup():
    d = request.get_json(silent=True) or {}
    name, email, pw = d.get("name", "").strip(), d.get("email", "").strip().lower(), d.get("password", "")
    if not name or len(name) > 60:
        return jsonify(error="Please enter your name."), 400
    if not EMAIL_RE.match(email):
        return jsonify(error="That email address doesn't look right."), 400
    if password_problem(pw):
        return jsonify(error=password_problem(pw)), 400
    try:
        cur = db().execute("INSERT INTO users(name,email,pw,created) VALUES(?,?,?,?)",
                           (name, email, generate_password_hash(pw), time.time()))
        db().commit()
    except sqlite3.IntegrityError:
        return jsonify(error="An account with this email already exists. Try logging in."), 409
    session["uid"] = cur.lastrowid
    return jsonify(ok=True)


@bp.post("/api/login")
def login():
    ip, now = request.remote_addr, time.time()
    _fails[ip] = [t for t in _fails.get(ip, []) if now - t < 60]
    if len(_fails[ip]) >= 5:
        return jsonify(error="Too many attempts. Wait a minute and try again."), 429
    d = request.get_json(silent=True) or {}
    u = db().execute("SELECT * FROM users WHERE email=?", (d.get("email", "").strip().lower(),)).fetchone()
    if not u or not check_password_hash(u["pw"], d.get("password", "")):
        _fails[ip].append(now)
        return jsonify(error="Incorrect email or password."), 401
    session["uid"] = u["id"]
    return jsonify(ok=True)


@bp.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@bp.get("/api/me")
@login_required
def me():
    u = db().execute("SELECT name,email FROM users WHERE id=?", (session["uid"],)).fetchone()
    if not u:
        session.clear()
        return jsonify(error="Please log in first."), 401
    return jsonify(name=u["name"], email=u["email"])


@bp.post("/api/forgot")
def forgot():
    email = (request.get_json(silent=True) or {}).get("email", "").strip().lower()
    u = db().execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
    out = dict(ok=True, message="If that email has an account, a reset link is on its way.")
    if u:
        token = secrets.token_urlsafe(24)
        db().execute("INSERT INTO resets(user_id,token,expires) VALUES(?,?,?)", (u["id"], _hash(token), time.time() + 900))
        db().commit()
        link = request.host_url + "login#reset=" + token
        print(f"\n[EMAIL SIMULATION] Password reset link for {email}:\n{link}\n")
        if os.getenv("DEMO_MODE", "1") != "0":  # no mail server in the demo, so show the link on screen
            out["demo_link"] = link
    return jsonify(out)


@bp.post("/api/reset")
def reset():
    d = request.get_json(silent=True) or {}
    pw = d.get("password", "")
    if password_problem(pw):
        return jsonify(error=password_problem(pw)), 400
    r = db().execute("SELECT * FROM resets WHERE token=? AND used=0 AND expires>?",
                     (_hash(d.get("token", "")), time.time())).fetchone()
    if not r:
        return jsonify(error="This reset link is invalid or has expired. Request a new one."), 400
    db().execute("UPDATE users SET pw=? WHERE id=?", (generate_password_hash(pw), r["user_id"]))
    db().execute("UPDATE resets SET used=1 WHERE id=?", (r["id"],))
    db().commit()
    return jsonify(ok=True)


# ---------------------------------------------------------------- history + stats
def save_history(uid, lang, code, result):
    hard = [e for e in result["errors"] if e["severity"] != "warning"]
    db().execute("INSERT INTO history(user_id,lang,code,errors,warnings,ok,phases,titles,created) VALUES(?,?,?,?,?,?,?,?,?)",
                 (uid, lang, code, len(hard), len(result["errors"]) - len(hard), int(not hard and not result["compiler_missing"]),
                  json.dumps([e["phase"] for e in hard]), json.dumps([e["title"] for e in hard]), time.time()))
    db().commit()


@bp.get("/api/history")
@login_required
def history():
    rows = db().execute("SELECT id,lang,code,errors,warnings,ok,created FROM history WHERE user_id=? ORDER BY created DESC LIMIT 20",
                        (session["uid"],)).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.get("/api/stats")
@login_required
def stats():
    rows = db().execute("SELECT * FROM history WHERE user_id=? ORDER BY created DESC LIMIT 500", (session["uid"],)).fetchall()
    phases, titles, langs = {}, {}, {}
    for r in rows:
        for p in json.loads(r["phases"]):
            phases[p] = phases.get(p, 0) + 1
        for t in json.loads(r["titles"]):
            titles[t] = titles.get(t, 0) + 1
        langs[r["lang"]] = langs.get(r["lang"], 0) + 1
    streak = 0
    for r in rows:
        if not r["ok"]:
            break
        streak += 1
    today = datetime.now().date()
    days = []
    for i in range(13, -1, -1):
        day = today - timedelta(days=i)
        n = sum(1 for r in rows if datetime.fromtimestamp(r["created"]).date() == day)
        days.append(dict(d=day.strftime("%d %b"), n=n))
    top = sorted(titles.items(), key=lambda x: -x[1])[:5]
    hint_counts = {r["level"]: r["n"] for r in db().execute(
        "SELECT level, COUNT(*) n FROM hints WHERE user_id=? GROUP BY level", (session["uid"],))}
    concepts = {}
    for t, n in titles.items():
        c = knowledge.concept_of(t)
        concepts[c] = concepts.get(c, 0) + n
    concept_list = sorted(concepts.items(), key=lambda x: -x[1])[:5]
    clean = sum(r["ok"] for r in rows)
    return jsonify(total=len(rows), clean=clean, rate=round(100 * clean / len(rows)) if rows else 0, streak=streak,
                   phases=phases, top=top, langs=langs, days=days, hints=hint_counts, concepts=concept_list,
                   insight=f"Your most common mistake is \u201c{top[0][0]}\u201d. Fixing this one habit would remove the most errors." if top else None)


@bp.post("/api/hint")
@login_required
def hint():
    d = request.get_json(silent=True) or {}
    if d.get("level") in ("gentle", "strong", "solution"):
        db().execute("INSERT INTO hints(user_id,title,level,created) VALUES(?,?,?,?)",
                     (session["uid"], str(d.get("title", ""))[:80], d["level"], time.time()))
        db().commit()
    return jsonify(ok=True)
