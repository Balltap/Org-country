#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Countryside Responsibility Map — SQLite backend
================================================
ใช้ Python standard library ล้วน ไม่ต้อง pip install อะไรเลย

วิธีรัน:   python3 server.py
เปิดเว็บ:  http://localhost:8787

ไฟล์ฐานข้อมูลคือ countryside.db (สร้างอัตโนมัติครั้งแรกที่รัน)
ครั้งแรกจะ seed ข้อมูลจาก seed.json ให้อัตโนมัติ
"""

import csv
import io
import json
import mimetypes
import os
import re
import sqlite3
import sys
import signal
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# DATA_DIR แยกจากโค้ด เพื่อให้ mount volume ใน Docker ได้
DATA_DIR = os.environ.get("DATA_DIR", BASE_DIR)
DB_PATH = os.path.join(DATA_DIR, "countryside.db")
SEED_PATH = os.path.join(BASE_DIR, "seed.json")
INDEX_FILE = "countryside_map_db.html"
PORT = int(os.environ.get("PORT", "8787"))
HOST = os.environ.get("HOST", "127.0.0.1")


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------

SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS departments (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS responsibilities (
    id            TEXT PRIMARY KEY,
    department_id TEXT NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    owner         TEXT NOT NULL DEFAULT 'ว่าง',
    scope         TEXT NOT NULL DEFAULT '',
    out_of_scope  TEXT NOT NULL DEFAULT '',
    color         TEXT NOT NULL DEFAULT '',
    kpi           TEXT NOT NULL DEFAULT '',
    sort_order    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_resp_dept  ON responsibilities(department_id);
CREATE INDEX IF NOT EXISTS idx_resp_owner ON responsibilities(owner);

CREATE TABLE IF NOT EXISTS audit_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    action    TEXT NOT NULL,
    entity    TEXT NOT NULL,
    entity_id TEXT,
    detail    TEXT
);

-- ปัญหาที่พบในแต่ละกล่องงาน (หนึ่งกล่องมีได้หลายปัญหา)
CREATE TABLE IF NOT EXISTS issues (
    id          TEXT PRIMARY KEY,
    item_id     TEXT NOT NULL REFERENCES responsibilities(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    detail      TEXT NOT NULL DEFAULT '',
    severity    TEXT NOT NULL DEFAULT 'medium',
    status      TEXT NOT NULL DEFAULT 'open',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_issue_item   ON issues(item_id);
CREATE INDEX IF NOT EXISTS idx_issue_status ON issues(status);
"""

SEVERITIES = ("high", "medium", "low")
SEVERITY_TH = {"high": "สูง", "medium": "กลาง", "low": "ต่ำ"}
SEVERITY_RANK = {"high": 1, "medium": 2, "low": 3}
RANK_SEVERITY = {1: "high", 2: "medium", 3: "low"}


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def log(conn, action, entity, entity_id=None, detail=""):
    conn.execute(
        "INSERT INTO audit_log (ts, action, entity, entity_id, detail) VALUES (?,?,?,?,?)",
        (now(), action, entity, entity_id, detail),
    )


def migrate(conn):
    """เพิ่มคอลัมน์ใหม่ให้ฐานข้อมูลเดิมที่สร้างไว้ก่อนหน้า"""
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(responsibilities)")]
    for col in ("out_of_scope", "color", "kpi"):
        if col not in cols:
            conn.execute(
                "ALTER TABLE responsibilities ADD COLUMN %s TEXT NOT NULL DEFAULT ''" % col
            )
            log(conn, "migrate", "database", None, "เพิ่มคอลัมน์ %s" % col)
            conn.commit()
            print("  ✓ อัปเกรดฐานข้อมูล: เพิ่มคอลัมน์ %s" % col)


def backfill_scopes(conn):
    """
    เติม scope / out_of_scope จาก seed.json ให้รายการที่ยังว่างอยู่
    แตะเฉพาะช่องที่ว่าง จึงไม่ทับข้อความที่ทีมแก้ไว้เอง
    """
    if not os.path.exists(SEED_PATH):
        return
    with io.open(SEED_PATH, encoding="utf-8") as f:
        seed = json.load(f)

    filled = 0
    for dept in seed:
        for item in dept.get("items", []):
            sc = item.get("scope", "")
            oos = item.get("out_of_scope", "")
            kpi = item.get("kpi", "")
            if not sc and not oos and not kpi:
                continue
            cur = conn.execute(
                "SELECT id, scope, out_of_scope, kpi FROM responsibilities WHERE name = ?",
                (item["name"],),
            ).fetchall()
            for row in cur:
                sets, vals = [], []
                if sc and not row["scope"]:
                    sets.append("scope=?"); vals.append(sc)
                if oos and not row["out_of_scope"]:
                    sets.append("out_of_scope=?"); vals.append(oos)
                if kpi and not row["kpi"]:
                    sets.append("kpi=?"); vals.append(kpi)
                if not sets:
                    continue
                sets.append("updated_at=?"); vals.append(now())
                vals.append(row["id"])
                conn.execute(
                    "UPDATE responsibilities SET %s WHERE id=?" % ", ".join(sets), vals
                )
                filled += 1

    if filled:
        log(conn, "update", "database", None, "เติมร่าง scope / KPI ให้ %d รายการ" % filled)
        conn.commit()
        print("  ✓ เติมร่าง scope / out of scope / KPI ให้ %d รายการ" % filled)


def init_db():
    if not os.path.isdir(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)
    fresh = not os.path.exists(DB_PATH)
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()
    migrate(conn)

    count = conn.execute("SELECT COUNT(*) c FROM departments").fetchone()["c"]
    if count == 0 and os.path.exists(SEED_PATH):
        with io.open(SEED_PATH, encoding="utf-8") as f:
            seed = json.load(f)
        ts = now()
        for di, dept in enumerate(seed):
            conn.execute(
                "INSERT INTO departments (id,name,sort_order,created_at,updated_at) VALUES (?,?,?,?,?)",
                (dept["id"], dept["name"], di, ts, ts),
            )
            for ii, item in enumerate(dept.get("items", [])):
                conn.execute(
                    "INSERT INTO responsibilities "
                    "(id,department_id,name,owner,scope,out_of_scope,color,kpi,"
                    "sort_order,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (str(uuid.uuid4()), dept["id"], item["name"],
                     item.get("owner", "ว่าง"), item.get("scope", ""),
                     item.get("out_of_scope", ""), item.get("color", ""),
                     item.get("kpi", ""), ii, ts, ts),
                )
        log(conn, "seed", "database", None,
            "นำเข้าข้อมูลตั้งต้น %d departments" % len(seed))
        conn.commit()
        print("  ✓ seed ข้อมูลตั้งต้นจาก seed.json แล้ว")

    backfill_scopes(conn)
    conn.close()
    if fresh:
        print("  ✓ สร้างฐานข้อมูลใหม่: %s" % DB_PATH)


# --------------------------------------------------------------------------
# Data access
# --------------------------------------------------------------------------

def get_state(conn):
    depts = conn.execute(
        "SELECT * FROM departments ORDER BY sort_order, name"
    ).fetchall()
    items = conn.execute(
        "SELECT * FROM responsibilities ORDER BY sort_order, created_at"
    ).fetchall()

    # สรุปจำนวนปัญหาของแต่ละกล่อง เพื่อให้หน้าเว็บขึ้น badge ได้โดยไม่ต้องยิง API ซ้ำ
    stats = {}
    for r in conn.execute(
        "SELECT item_id, "
        "SUM(CASE WHEN status='open' THEN 1 ELSE 0 END) open_n, "
        "COUNT(*) total_n, "
        "MIN(CASE WHEN status='open' THEN "
        "     CASE severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END "
        "   ELSE 9 END) top_rank "
        "FROM issues GROUP BY item_id"
    ):
        stats[r["item_id"]] = {
            "issues_open": r["open_n"],
            "issues_total": r["total_n"],
            "top_severity": RANK_SEVERITY.get(r["top_rank"], ""),
        }

    by_dept = {}
    for r in items:
        st = stats.get(r["id"], {})
        by_dept.setdefault(r["department_id"], []).append({
            "id": r["id"],
            "name": r["name"],
            "owner": r["owner"],
            "scope": r["scope"],
            "out_of_scope": r["out_of_scope"],
            "color": r["color"],
            "kpi": r["kpi"],
            "order": r["sort_order"],
            "issues_open": st.get("issues_open", 0),
            "issues_total": st.get("issues_total", 0),
            "top_severity": st.get("top_severity", ""),
        })

    return {
        "departments": [{
            "id": d["id"],
            "name": d["name"],
            "order": d["sort_order"],
            "items": by_dept.get(d["id"], []),
        } for d in depts],
        "server_time": now(),
    }


def next_dept_order(conn):
    row = conn.execute("SELECT COALESCE(MAX(sort_order),-1)+1 n FROM departments").fetchone()
    return row["n"]


def next_item_order(conn, dept_id):
    row = conn.execute(
        "SELECT COALESCE(MAX(sort_order),-1)+1 n FROM responsibilities WHERE department_id=?",
        (dept_id,),
    ).fetchone()
    return row["n"]


# --------------------------------------------------------------------------
# API handlers — แต่ละตัวคืน (status_code, payload_dict)
# --------------------------------------------------------------------------

def api_state(conn, body, query):
    return 200, get_state(conn)


def api_create_department(conn, body, query):
    name = (body.get("name") or "").strip()
    if not name:
        return 400, {"error": "ต้องระบุชื่อ Department"}

    dup = conn.execute(
        "SELECT id FROM departments WHERE lower(name)=lower(?)", (name,)
    ).fetchone()
    if dup:
        return 409, {"error": "มี Department ชื่อนี้อยู่แล้ว"}

    new_id = str(uuid.uuid4())
    ts = now()
    conn.execute(
        "INSERT INTO departments (id,name,sort_order,created_at,updated_at) VALUES (?,?,?,?,?)",
        (new_id, name, next_dept_order(conn), ts, ts),
    )
    log(conn, "create", "department", new_id, name)
    conn.commit()
    return 201, {"id": new_id, "state": get_state(conn)}


def api_update_department(conn, body, query, dept_id):
    name = (body.get("name") or "").strip()
    if not name:
        return 400, {"error": "ต้องระบุชื่อ Department"}

    row = conn.execute("SELECT name FROM departments WHERE id=?", (dept_id,)).fetchone()
    if not row:
        return 404, {"error": "ไม่พบ Department"}

    dup = conn.execute(
        "SELECT id FROM departments WHERE lower(name)=lower(?) AND id<>?", (name, dept_id)
    ).fetchone()
    if dup:
        return 409, {"error": "มี Department ชื่อนี้อยู่แล้ว"}

    conn.execute(
        "UPDATE departments SET name=?, updated_at=? WHERE id=?", (name, now(), dept_id)
    )
    log(conn, "update", "department", dept_id, "%s → %s" % (row["name"], name))
    conn.commit()
    return 200, {"state": get_state(conn)}


def api_delete_department(conn, body, query, dept_id):
    row = conn.execute("SELECT name FROM departments WHERE id=?", (dept_id,)).fetchone()
    if not row:
        return 404, {"error": "ไม่พบ Department"}

    n = conn.execute(
        "SELECT COUNT(*) c FROM responsibilities WHERE department_id=?", (dept_id,)
    ).fetchone()["c"]

    move_to = (query.get("moveTo", [""])[0] or "").strip()

    if n > 0 and not move_to:
        return 409, {"error": "Department นี้ยังมี %d responsibilities" % n, "items": n}

    if n > 0:
        dest = conn.execute("SELECT name FROM departments WHERE id=?", (move_to,)).fetchone()
        if not dest:
            return 400, {"error": "ไม่พบ Department ปลายทาง"}
        base = next_item_order(conn, move_to)
        moving = conn.execute(
            "SELECT id FROM responsibilities WHERE department_id=? ORDER BY sort_order", (dept_id,)
        ).fetchall()
        for offset, r in enumerate(moving):
            conn.execute(
                "UPDATE responsibilities SET department_id=?, sort_order=?, updated_at=? WHERE id=?",
                (move_to, base + offset, now(), r["id"]),
            )
        log(conn, "move", "department", dept_id,
            "ย้าย %d รายการ: %s → %s" % (n, row["name"], dest["name"]))

    conn.execute("DELETE FROM departments WHERE id=?", (dept_id,))
    log(conn, "delete", "department", dept_id, row["name"])
    conn.commit()
    return 200, {"state": get_state(conn)}


def api_create_item(conn, body, query):
    dept_id = (body.get("department_id") or "").strip()
    name = (body.get("name") or "").strip()
    owner = (body.get("owner") or "").strip()
    scope = (body.get("scope") or "").strip()
    out_of_scope = (body.get("out_of_scope") or "").strip()
    color = (body.get("color") or "").strip()
    kpi = (body.get("kpi") or "").strip()

    if not name or not owner:
        return 400, {"error": "ต้องระบุ Responsibility และ Owner"}
    if not conn.execute("SELECT 1 FROM departments WHERE id=?", (dept_id,)).fetchone():
        return 400, {"error": "ไม่พบ Department"}

    new_id = str(uuid.uuid4())
    ts = now()
    conn.execute(
        "INSERT INTO responsibilities "
        "(id,department_id,name,owner,scope,out_of_scope,color,kpi,"
        "sort_order,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (new_id, dept_id, name, owner, scope, out_of_scope, color, kpi,
         next_item_order(conn, dept_id), ts, ts),
    )
    log(conn, "create", "responsibility", new_id, "%s — %s" % (name, owner))
    conn.commit()
    return 201, {"id": new_id, "state": get_state(conn)}


def api_update_item(conn, body, query, item_id):
    row = conn.execute("SELECT * FROM responsibilities WHERE id=?", (item_id,)).fetchone()
    if not row:
        return 404, {"error": "ไม่พบ Responsibility"}

    name = (body.get("name") or "").strip()
    owner = (body.get("owner") or "").strip()
    scope = (body.get("scope") or "").strip()
    out_of_scope = (body.get("out_of_scope") or "").strip()
    color = (body.get("color") or "").strip()
    kpi = (body.get("kpi") or "").strip()
    dept_id = (body.get("department_id") or row["department_id"]).strip()

    if not name or not owner:
        return 400, {"error": "ต้องระบุ Responsibility และ Owner"}
    if not conn.execute("SELECT 1 FROM departments WHERE id=?", (dept_id,)).fetchone():
        return 400, {"error": "ไม่พบ Department"}

    order = row["sort_order"]
    if dept_id != row["department_id"]:
        order = next_item_order(conn, dept_id)

    conn.execute(
        "UPDATE responsibilities SET department_id=?, name=?, owner=?, scope=?, "
        "out_of_scope=?, color=?, kpi=?, sort_order=?, updated_at=? WHERE id=?",
        (dept_id, name, owner, scope, out_of_scope, color, kpi, order, now(), item_id),
    )

    changes = []
    if row["name"] != name:
        changes.append("ชื่อ: %s → %s" % (row["name"], name))
    if row["owner"] != owner:
        changes.append("ผู้รับผิดชอบ: %s → %s" % (row["owner"], owner))
    if row["department_id"] != dept_id:
        changes.append("ย้าย department")
    if row["scope"] != scope or row["out_of_scope"] != out_of_scope:
        changes.append("แก้ไข scope")
    if row["color"] != color:
        changes.append("เปลี่ยนสีกำกับ")
    if row["kpi"] != kpi:
        changes.append("แก้ไข KPI")
    log(conn, "update", "responsibility", item_id, " | ".join(changes) or name)
    conn.commit()
    return 200, {"state": get_state(conn)}


def api_delete_item(conn, body, query, item_id):
    row = conn.execute("SELECT name, owner FROM responsibilities WHERE id=?", (item_id,)).fetchone()
    if not row:
        return 404, {"error": "ไม่พบ Responsibility"}
    conn.execute("DELETE FROM responsibilities WHERE id=?", (item_id,))
    log(conn, "delete", "responsibility", item_id, "%s — %s" % (row["name"], row["owner"]))
    conn.commit()
    return 200, {"state": get_state(conn)}


def api_health(conn, body, query):
    d = conn.execute("SELECT COUNT(*) c FROM departments").fetchone()["c"]
    r = conn.execute("SELECT COUNT(*) c FROM responsibilities").fetchone()["c"]
    i = conn.execute("SELECT COUNT(*) c FROM issues WHERE status='open'").fetchone()["c"]
    return 200, {"status": "ok", "departments": d, "responsibilities": r,
                 "open_issues": i, "time": now()}


def api_reorder(conn, body, query):
    """
    รับลำดับใหม่ของกล่องหลังลากวาง
    body = {"order": {"<department_id>": ["<item_id>", ...], ...}}
    อัปเดตทั้ง department_id และ sort_order ให้ตรงกับลำดับที่ส่งมา
    """
    order = body.get("order") or {}
    if not isinstance(order, dict) or not order:
        return 400, {"error": "ไม่มีข้อมูลลำดับที่ส่งมา"}

    known = {r["id"] for r in conn.execute("SELECT id FROM departments")}
    moved = 0
    ts = now()

    for dept_id, ids in order.items():
        if dept_id not in known:
            return 400, {"error": "ไม่พบ Department: %s" % dept_id}
        for pos, item_id in enumerate(ids):
            row = conn.execute(
                "SELECT department_id, sort_order, name FROM responsibilities WHERE id=?",
                (item_id,),
            ).fetchone()
            if not row:
                continue
            if row["department_id"] != dept_id or row["sort_order"] != pos:
                conn.execute(
                    "UPDATE responsibilities SET department_id=?, sort_order=?, updated_at=? "
                    "WHERE id=?",
                    (dept_id, pos, ts, item_id),
                )
                if row["department_id"] != dept_id:
                    moved += 1

    log(conn, "move", "responsibility", None,
        "จัดลำดับกล่องใหม่%s" % (" (ย้ายข้าม department %d รายการ)" % moved if moved else ""))
    conn.commit()
    return 200, {"state": get_state(conn)}


# ---------------------------- Issues ---------------------------------------

def issue_rows(conn, where="", params=()):
    """คืนรายการปัญหาพร้อมชื่อกล่องงานและ department เพื่อใช้ได้ทั้งสองหน้าจอ"""
    rows = conn.execute(
        "SELECT i.*, r.name item_name, r.owner item_owner, "
        "       d.id dept_id, d.name dept_name "
        "FROM issues i "
        "JOIN responsibilities r ON r.id = i.item_id "
        "JOIN departments d      ON d.id = r.department_id "
        + (("WHERE " + where + " ") if where else "")
        + "ORDER BY (i.status='open') DESC, "
          "CASE i.severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, "
          "i.created_at DESC",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def api_issues(conn, body, query):
    """GET /api/issues            → ปัญหาทั้งระบบ (หน้ารวม)
       GET /api/issues?item_id=.. → เฉพาะกล่องเดียว"""
    item_id = (query.get("item_id", [""])[0] or "").strip()
    if item_id:
        issues = issue_rows(conn, "i.item_id = ?", (item_id,))
    else:
        issues = issue_rows(conn)

    summary = {"total": len(issues), "open": 0, "resolved": 0,
               "high": 0, "medium": 0, "low": 0}
    for it in issues:
        if it["status"] == "open":
            summary["open"] += 1
            summary[it["severity"]] = summary.get(it["severity"], 0) + 1
        else:
            summary["resolved"] += 1

    return 200, {"issues": issues, "summary": summary}


def api_create_issue(conn, body, query):
    item_id = (body.get("item_id") or "").strip()
    title = (body.get("title") or "").strip()
    detail = (body.get("detail") or "").strip()
    severity = (body.get("severity") or "medium").strip().lower()

    if severity not in SEVERITIES:
        severity = "medium"
    if not title:
        return 400, {"error": "ต้องระบุหัวข้อปัญหา"}

    item = conn.execute(
        "SELECT name FROM responsibilities WHERE id=?", (item_id,)
    ).fetchone()
    if not item:
        return 400, {"error": "ไม่พบกล่องงานนี้"}

    new_id = str(uuid.uuid4())
    ts = now()
    conn.execute(
        "INSERT INTO issues (id,item_id,title,detail,severity,status,created_at,updated_at) "
        "VALUES (?,?,?,?,?,'open',?,?)",
        (new_id, item_id, title, detail, severity, ts, ts),
    )
    log(conn, "create", "issue", new_id,
        "แจ้งปัญหา [%s] %s — %s" % (SEVERITY_TH[severity], title, item["name"]))
    conn.commit()
    return 201, {"id": new_id, "state": get_state(conn)}


def api_update_issue(conn, body, query, issue_id):
    row = conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
    if not row:
        return 404, {"error": "ไม่พบปัญหานี้"}

    title = (body.get("title") or row["title"]).strip()
    detail = body.get("detail")
    detail = row["detail"] if detail is None else str(detail).strip()
    severity = (body.get("severity") or row["severity"]).strip().lower()
    status = (body.get("status") or row["status"]).strip().lower()

    if not title:
        return 400, {"error": "ต้องระบุหัวข้อปัญหา"}
    if severity not in SEVERITIES:
        severity = row["severity"]
    if status not in ("open", "resolved"):
        status = row["status"]

    ts = now()
    resolved_at = row["resolved_at"]
    if status == "resolved" and row["status"] != "resolved":
        resolved_at = ts
    if status == "open":
        resolved_at = None

    conn.execute(
        "UPDATE issues SET title=?, detail=?, severity=?, status=?, "
        "resolved_at=?, updated_at=? WHERE id=?",
        (title, detail, severity, status, resolved_at, ts, issue_id),
    )

    changes = []
    if row["title"] != title:
        changes.append("หัวข้อ: %s → %s" % (row["title"], title))
    if row["detail"] != detail:
        changes.append("แก้รายละเอียด")
    if row["severity"] != severity:
        changes.append("ความรุนแรง: %s → %s"
                       % (SEVERITY_TH.get(row["severity"], row["severity"]),
                          SEVERITY_TH[severity]))
    if row["status"] != status:
        changes.append("ปิดปัญหาแล้ว" if status == "resolved" else "เปิดปัญหาใหม่")
    log(conn, "update", "issue", issue_id, " | ".join(changes) or title)
    conn.commit()
    return 200, {"state": get_state(conn)}


def api_delete_issue(conn, body, query, issue_id):
    row = conn.execute("SELECT title FROM issues WHERE id=?", (issue_id,)).fetchone()
    if not row:
        return 404, {"error": "ไม่พบปัญหานี้"}
    conn.execute("DELETE FROM issues WHERE id=?", (issue_id,))
    log(conn, "delete", "issue", issue_id, "ลบปัญหา: %s" % row["title"])
    conn.commit()
    return 200, {"state": get_state(conn)}


def api_history(conn, body, query):
    limit = int(query.get("limit", ["60"])[0])
    rows = conn.execute(
        "SELECT ts, action, entity, detail FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return 200, {"history": [dict(r) for r in rows]}


ROUTES = [
    ("GET",    r"^/api/health$",             api_health),
    ("GET",    r"^/api/state$",              api_state),
    ("GET",    r"^/api/history$",            api_history),
    ("POST",   r"^/api/departments$",        api_create_department),
    ("PUT",    r"^/api/departments/([\w-]+)$", api_update_department),
    ("DELETE", r"^/api/departments/([\w-]+)$", api_delete_department),
    ("POST",   r"^/api/items$",              api_create_item),
    ("POST",   r"^/api/reorder$",            api_reorder),
    ("PUT",    r"^/api/items/([\w-]+)$",     api_update_item),
    ("DELETE", r"^/api/items/([\w-]+)$",     api_delete_item),
    ("GET",    r"^/api/issues$",             api_issues),
    ("POST",   r"^/api/issues$",             api_create_issue),
    ("PUT",    r"^/api/issues/([\w-]+)$",    api_update_issue),
    ("DELETE", r"^/api/issues/([\w-]+)$",    api_delete_issue),
]


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "CountrysideMap/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s  %s\n" % (self.log_date_time_string(), fmt % args))

    # ---- helpers ----
    def send_json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def dispatch(self, method):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path.startswith("/api/"):
            if path == "/api/export.csv" and method == "GET":
                return self.export_csv()
            if path == "/api/backup.db" and method == "GET":
                return self.backup_db()

            body = self.read_body() if method in ("POST", "PUT", "DELETE") else {}
            for m, pattern, fn in ROUTES:
                if m != method:
                    continue
                match = re.match(pattern, path)
                if match:
                    conn = connect()
                    try:
                        status, payload = fn(conn, body, query, *match.groups())
                    except sqlite3.Error as e:
                        conn.rollback()
                        status, payload = 500, {"error": "ฐานข้อมูลผิดพลาด: %s" % e}
                    finally:
                        conn.close()
                    return self.send_json(status, payload)
            return self.send_json(404, {"error": "ไม่พบ endpoint นี้"})

        if method != "GET":
            return self.send_json(405, {"error": "method not allowed"})
        return self.serve_static(path)

    # ---- static ----
    def serve_static(self, path):
        rel = INDEX_FILE if path in ("/", "") else path.lstrip("/")
        full = os.path.normpath(os.path.join(BASE_DIR, rel))
        if not full.startswith(BASE_DIR) or not os.path.isfile(full):
            self.send_error(404, "File not found")
            return
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype == "application/javascript":
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    # ---- extras ----
    def export_csv(self):
        conn = connect()
        state = get_state(conn)
        conn.close()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Department", "Responsibility", "Owner",
                    "Scope (ทำ)", "Out of Scope (ไม่ทำ)", "KPI", "Color",
                    "ปัญหาที่ยังเปิด"])
        for d in state["departments"]:
            for it in d["items"]:
                w.writerow([d["name"], it["name"], it["owner"],
                            it["scope"], it["out_of_scope"],
                            it["kpi"], it["color"],
                            it.get("issues_open", 0)])
        data = ("\ufeff" + buf.getvalue()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition",
                         'attachment; filename="countryside_responsibilities.csv"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def backup_db(self):
        conn = connect()
        conn.execute("PRAGMA wal_checkpoint(FULL)")
        conn.close()
        with open(DB_PATH, "rb") as f:
            data = f.read()
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition",
                         'attachment; filename="countryside_backup_%s.db"' % stamp)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_PUT(self):
        self.dispatch("PUT")

    def do_DELETE(self):
        self.dispatch("DELETE")


def main():
    print("")
    print("  🎋 Countryside Responsibility Map — SQLite server")
    print("  " + "-" * 50)
    init_db()
    conn = connect()
    d = conn.execute("SELECT COUNT(*) c FROM departments").fetchone()["c"]
    r = conn.execute("SELECT COUNT(*) c FROM responsibilities").fetchone()["c"]
    conn.close()
    print("  ✓ ข้อมูลปัจจุบัน: %d departments, %d responsibilities" % (d, r))
    print("")
    print("  ไฟล์ฐานข้อมูล: %s" % DB_PATH)
    print("  เปิดเบราว์เซอร์ที่ →  http://%s:%d" % (HOST, PORT))
    print("  กด Ctrl+C เพื่อหยุด server")
    print("")

    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    httpd.daemon_threads = True

    def shutdown(signum, frame):
        print("\n  ได้รับสัญญาณหยุด (%s) กำลังปิด server..." % signum)
        conn = connect()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
        httpd.shutdown()

    # SIGTERM คือสัญญาณที่ docker stop ส่งมา ต้องรับเพื่อปิด WAL ให้เรียบร้อย
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
        print("  หยุด server แล้ว ข้อมูลถูกบันทึกไว้ใน %s\n" % DB_PATH)


if __name__ == "__main__":
    main()
