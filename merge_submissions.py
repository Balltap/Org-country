#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
รวมไฟล์ data.json ที่แต่ละคนแก้แล้วส่งกลับมา เข้าฐานข้อมูล countryside.db
=========================================================================
วิธีใช้:
    python merge_submissions.py data-คุณเฟย์.json data-คุณนิค.json
    python merge_submissions.py submissions/          (ทั้งโฟลเดอร์)
    python merge_submissions.py --dry-run data-*.json (ดูก่อนว่าจะเปลี่ยนอะไร)

ระบบจะแตะเฉพาะกล่องงานที่มีเครื่องหมาย edited จากหน้าเว็บเท่านั้น
กล่องที่คนนั้นไม่ได้แก้ จะไม่ถูกเขียนทับ แม้จะอยู่ในไฟล์เดียวกัน
ทุกการเปลี่ยนแปลงถูกบันทึกลง audit_log พร้อมชื่อผู้ส่ง
"""

import glob
import io
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "countryside.db")

ISSUES_DDL = """
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


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def log(conn, action, entity, entity_id, detail):
    conn.execute(
        "INSERT INTO audit_log (ts, action, entity, entity_id, detail) VALUES (?,?,?,?,?)",
        (now(), action, entity, entity_id, detail),
    )


def collect_files(args):
    files = []
    for a in args:
        if os.path.isdir(a):
            files += sorted(glob.glob(os.path.join(a, "*.json")))
        else:
            files += sorted(glob.glob(a)) or [a]
    seen, out = set(), []
    for f in files:
        f = os.path.abspath(f)
        if f not in seen and os.path.isfile(f):
            seen.add(f)
            out.append(f)
    return out


def merge_file(conn, path, dry):
    with io.open(path, encoding="utf-8") as f:
        data = json.load(f)

    who = (data.get("submitted_by") or "ไม่ระบุชื่อ").strip()
    name = os.path.basename(path)
    changes = []

    for dept in data.get("departments", []):
        for item in dept.get("items", []):
            if not item.get("edited"):
                continue

            row = conn.execute(
                "SELECT id, name, scope, out_of_scope, kpi FROM responsibilities WHERE id=?",
                (item.get("id"),),
            ).fetchone()
            if not row:
                changes.append("  ⚠ ข้ามกล่อง \"%s\" — ไม่พบรหัสนี้ในฐานข้อมูลแล้ว" % item.get("name"))
                continue

            label = row["name"]
            sets, vals, what = [], [], []
            for key, col, th in (("scope", "scope", "Scope"),
                                 ("out_of_scope", "out_of_scope", "Out of Scope"),
                                 ("kpi", "kpi", "KPI")):
                new = (item.get(key) or "").strip()
                if new != (row[col] or ""):
                    sets.append("%s=?" % col)
                    vals.append(new)
                    what.append(th)

            if sets:
                sets.append("updated_at=?")
                vals.append(now())
                vals.append(row["id"])
                if not dry:
                    conn.execute("UPDATE responsibilities SET %s WHERE id=?" % ", ".join(sets), vals)
                    log(conn, "update", "responsibility", row["id"],
                        "[%s] แก้ %s — %s" % (who, " / ".join(what), label))
                changes.append("  ✎ %s — แก้ %s" % (label, " / ".join(what)))

            # ----- ปัญหา -----
            submitted = item.get("issues") or []
            existing = {r["id"]: r for r in conn.execute(
                "SELECT * FROM issues WHERE item_id=?", (row["id"],))}
            keep = set()

            for iss in submitted:
                iid = str(iss.get("id") or "")
                title = (iss.get("title") or "").strip()
                detail = (iss.get("detail") or "").strip()
                sev = (iss.get("severity") or "medium").lower()
                status = (iss.get("status") or "open").lower()
                if sev not in SEVERITIES:
                    sev = "medium"
                if status not in ("open", "resolved"):
                    status = "open"
                if not title:
                    continue

                # ปัญหาที่เพิ่มใหม่จากหน้าเว็บจะมี id ขึ้นต้นด้วย "new-"
                # ถ้ากล่องนี้มีปัญหาหัวข้อเดียวกันอยู่แล้ว ให้ถือเป็นตัวเดียวกัน
                # (กันกรณีรวมไฟล์เดิมซ้ำสองรอบ แล้วได้ปัญหาซ้ำ)
                if iid not in existing:
                    for eid, e in existing.items():
                        if (e["title"] or "").strip() == title:
                            iid = eid
                            break

                if iid in existing:
                    keep.add(iid)
                    old = existing[iid]
                    if (old["title"], old["detail"], old["severity"], old["status"]) != \
                       (title, detail, sev, status):
                        if not dry:
                            conn.execute(
                                "UPDATE issues SET title=?, detail=?, severity=?, status=?, updated_at=? "
                                "WHERE id=?", (title, detail, sev, status, now(), iid))
                            log(conn, "update", "issue", iid, "[%s] แก้ปัญหา: %s" % (who, title))
                        changes.append("  ✎ %s — แก้ปัญหา \"%s\"" % (label, title))
                else:
                    new_id = str(uuid.uuid4())
                    if not dry:
                        ts = now()
                        conn.execute(
                            "INSERT INTO issues (id,item_id,title,detail,severity,status,created_at,updated_at) "
                            "VALUES (?,?,?,?,?,?,?,?)",
                            (new_id, row["id"], title, detail, sev, status, ts, ts))
                        log(conn, "create", "issue", new_id,
                            "[%s] แจ้งปัญหา: %s — %s" % (who, title, label))
                    changes.append("  ＋ %s — ปัญหาใหม่ \"%s\" (%s)" % (label, title, sev))

            for iid, old in existing.items():
                if iid not in keep:
                    if not dry:
                        conn.execute("DELETE FROM issues WHERE id=?", (iid,))
                        log(conn, "delete", "issue", iid,
                            "[%s] ลบปัญหา: %s" % (who, old["title"]))
                    changes.append("  － %s — ลบปัญหา \"%s\"" % (label, old["title"]))

    print("\n📄 %s   (ผู้ส่ง: %s)" % (name, who))
    if changes:
        for c in changes:
            print(c)
    else:
        print("  (ไม่มีการเปลี่ยนแปลง)")
    return len(changes)


def main():
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    dry = "--dry-run" in sys.argv[1:]

    if not args:
        print(__doc__)
        sys.exit(1)
    if not os.path.exists(DB_PATH):
        sys.exit("ไม่พบฐานข้อมูล %s" % DB_PATH)

    files = collect_files(args)
    if not files:
        sys.exit("ไม่พบไฟล์ที่ระบุ")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(ISSUES_DDL)
    conn.commit()

    print("")
    print("  รวมข้อมูลเข้า %s%s" % (DB_PATH, "   [โหมดทดลอง ไม่เขียนจริง]" if dry else ""))
    print("  " + "-" * 60)

    total = 0
    for path in files:
        try:
            total += merge_file(conn, path, dry)
        except json.JSONDecodeError as e:
            print("\n📄 %s\n  ⚠ ไฟล์เสียหาย อ่านไม่ได้: %s" % (os.path.basename(path), e))
        except Exception as e:
            conn.rollback()
            print("\n📄 %s\n  ⚠ ผิดพลาด: %s" % (os.path.basename(path), e))

    if dry:
        conn.rollback()
    else:
        conn.commit()
    conn.close()

    print("")
    print("  " + "-" * 60)
    print("  รวม %d ไฟล์ · %d การเปลี่ยนแปลง%s" % (len(files), total, " (ยังไม่เขียนจริง)" if dry else ""))
    if total and not dry:
        print("")
        print("  ขั้นตอนถัดไป — อัปเดตเว็บสาธารณะ:")
        print("    python build_static.py")
        print("    git add index.html data.json && git commit -m \"merge submissions\" && git push")
    print("")


if __name__ == "__main__":
    main()
