#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
สร้างเว็บสาธารณะ (index.html + data.json) จากฐานข้อมูล countryside.db
=====================================================================
ผลลัพธ์ 2 ไฟล์ ใช้คู่กัน วางบน GitHub Pages ได้เลย ไม่ต้องมี server

  data.json   ข้อมูลทั้งหมด (departments / กล่องงาน / scope / KPI / ปัญหา)
  index.html  หน้าเว็บที่อ่าน data.json มาแสดง และให้แต่ละคนแก้ของตัวเองได้
              แล้วกดดาวน์โหลด data.json ฉบับที่แก้แล้ว ส่งกลับให้ผู้ประสานงาน

วิธีใช้:  python build_static.py
จากนั้น:  git add index.html data.json && git commit -m "update public map" && git push
"""

import json
import os
import re
import sqlite3
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "countryside.db")
APP_HTML = os.path.join(BASE_DIR, "countryside_map_db.html")
OUT_HTML = os.path.join(BASE_DIR, "index.html")
OUT_JSON = os.path.join(BASE_DIR, "data.json")

TH_MONTHS = ["", "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
             "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]


def thai_stamp(dt):
    return "%d %s %d เวลา %02d:%02d น." % (
        dt.day, TH_MONTHS[dt.month], dt.year + 543, dt.hour, dt.minute)


def read_css():
    """ดึง CSS จากหน้าเว็บตัวจริง เพื่อให้หน้าสาธารณะหน้าตาเหมือนกันเสมอ"""
    with open(APP_HTML, encoding="utf-8") as f:
        src = f.read()
    m = re.search(r"<style>(.*?)</style>", src, re.S)
    if not m:
        sys.exit("หา <style> ในไฟล์ %s ไม่เจอ" % APP_HTML)
    return m.group(1)


def load_data():
    if not os.path.exists(DB_PATH):
        sys.exit("ไม่พบไฟล์ฐานข้อมูล %s" % DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    has_issues = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='issues'"
    ).fetchone() is not None

    issues_by_item = {}
    if has_issues:
        for r in conn.execute(
            "SELECT id, item_id, title, detail, severity, status FROM issues "
            "ORDER BY CASE severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, created_at"
        ):
            issues_by_item.setdefault(r["item_id"], []).append({
                "id": r["id"], "title": r["title"], "detail": r["detail"],
                "severity": r["severity"], "status": r["status"],
            })

    depts = []
    for d in conn.execute("SELECT * FROM departments ORDER BY sort_order, name"):
        items = []
        for r in conn.execute(
            "SELECT * FROM responsibilities WHERE department_id=? ORDER BY sort_order, created_at",
            (d["id"],),
        ):
            items.append({
                "id": r["id"], "name": r["name"], "owner": r["owner"],
                "scope": r["scope"], "out_of_scope": r["out_of_scope"],
                "kpi": r["kpi"], "color": r["color"],
                "issues": issues_by_item.get(r["id"], []),
            })
        depts.append({"id": d["id"], "name": d["name"], "items": items})
    conn.close()
    return depts


def main():
    css = read_css()
    depts = load_data()
    now = datetime.now()
    stamp = thai_stamp(now)

    payload = {
        "version": 1,
        "generated_at": now.isoformat(timespec="seconds"),
        "generated_stamp": stamp,
        "departments": depts,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    with open(os.path.join(BASE_DIR, "_template.html"), encoding="utf-8") as f:
        template = f.read()
    out = template.replace("/*__CSS__*/", css)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(out)

    n_items = sum(len(d["items"]) for d in depts)
    n_issues = sum(len(i["issues"]) for d in depts for i in d["items"])
    print("")
    print("  ✓ data.json   %d departments · %d กล่องงาน · %d ปัญหา" % (len(depts), n_items, n_issues))
    print("  ✓ index.html  ข้อมูล ณ %s" % stamp)
    print("")
    print("  ขั้นตอนถัดไป:")
    print("    git add index.html data.json")
    print("    git commit -m \"update public map\"")
    print("    git push")
    print("")


if __name__ == "__main__":
    main()
