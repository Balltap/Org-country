#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
สร้างหน้าเว็บแบบอ่านอย่างเดียว (index.html) สำหรับ GitHub Pages
===============================================================
ดึงข้อมูลจาก countryside.db แล้วฝังลงไฟล์ HTML ไฟล์เดียว เปิดได้โดยไม่ต้องมี server

วิธีใช้:   python build_static.py
ผลลัพธ์:   index.html  (push ขึ้น GitHub แล้วเปิด GitHub Pages ได้เลย)

ทุกครั้งที่แก้ข้อมูลในระบบแล้วอยากให้เว็บสาธารณะอัปเดตตาม ให้รันคำสั่งนี้ซ้ำ
แล้ว git add / commit / push
"""

import html
import json
import os
import re
import sqlite3
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "countryside.db")
APP_HTML = os.path.join(BASE_DIR, "countryside_map_db.html")
OUT_PATH = os.path.join(BASE_DIR, "index.html")

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
            "SELECT item_id, title, detail, severity, status FROM issues "
            "WHERE status='open' "
            "ORDER BY CASE severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, "
            "created_at DESC"
        ):
            issues_by_item.setdefault(r["item_id"], []).append(dict(r))

    depts = []
    for d in conn.execute("SELECT * FROM departments ORDER BY sort_order, name"):
        items = []
        for r in conn.execute(
            "SELECT * FROM responsibilities WHERE department_id=? ORDER BY sort_order, created_at",
            (d["id"],),
        ):
            iss = issues_by_item.get(r["id"], [])
            items.append({
                "name": r["name"], "owner": r["owner"],
                "scope": r["scope"], "out_of_scope": r["out_of_scope"],
                "kpi": r["kpi"], "color": r["color"],
                "issues": iss,
            })
        depts.append({"name": d["name"], "items": items})
    conn.close()
    return depts


TEMPLATE = """<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Countryside shape the future — Responsibility Map</title>
<style>
__CSS__
  /* ---- ส่วนเพิ่มเฉพาะหน้าสาธารณะ (อ่านอย่างเดียว) ---- */
  .card{cursor:default}
  .card:active{cursor:default}
  .readonly-note{
    margin:0 0 16px;padding:11px 15px;background:#eaf3ff;border:1px solid #a6c8f5;
    border-radius:11px;font-size:12.5px;line-height:1.6;color:#0f3f86
  }
  .readonly-note b{color:#0a2d61}
  .stamp{font-size:12px;color:var(--muted);font-weight:700}
  .issue-list-card{
    margin-top:8px;padding-top:7px;border-top:1px dashed #dfe6ea;
    display:flex;flex-direction:column;gap:4px
  }
  .issue-mini{display:flex;gap:6px;font-size:11.5px;line-height:1.5;color:#7d2420}
  .issue-mini .dot{flex:0 0 auto;font-size:9px;line-height:1.7}
  .issue-mini.medium{color:#8a5d10}
  .issue-mini.low{color:#0f5fd6}
</style>
</head>
<body>
<div class="app">
  <div class="shell">
    <header class="header">
      <div>
        <div class="eyebrow">Project Workspace</div>
        <h1>🎋 Countryside shape the future</h1>
        <p class="subtitle">Project Responsibility Map · <span class="stamp">ข้อมูล ณ __STAMP__</span></p>
      </div>
      <div class="header-actions">
        <div class="search-wrap">
          <span class="search-icon">⌕</span>
          <input id="search" class="search" placeholder="ค้นหางาน หรือชื่อผู้รับผิดชอบ..." />
        </div>
        <button class="btn" onclick="exportPDF()" title="พิมพ์หรือบันทึกเป็น PDF">🖨 PDF</button>
      </div>
    </header>

    <div class="readonly-note">
      <b>หน้านี้เป็นฉบับอ่านอย่างเดียว</b> — เป็นภาพนิ่งของข้อมูล ณ วันที่ระบุด้านบน แก้ไขในหน้านี้ไม่ได้ ·
      ขอบเขตงาน (✅ ทำ / ❌ ไม่ทำ) และ KPI ทั้งหมดยังเป็น <b>ร่างที่รอการยืนยันจากเจ้าของงาน</b> ·
      เลื่อนเมาส์ค้างบนการ์ดเพื่อดูข้อความเต็ม · ต้องการแก้ไขข้อมูล แจ้งผู้ประสานงานโครงการ (คุณบอล)
    </div>

    <div class="print-only print-head">
      <h1>🎋 Countryside shape the future — Project Responsibility Map</h1>
      <div class="meta" id="printMeta"></div>
    </div>

    <section class="frame">
      <div class="frame-head">
        <div class="frame-eyebrow">Program Framework</div>
        <div class="frame-title">🎋 Countryside shape the future</div>
        <div class="frame-sub">ทุก Department และทุกความรับผิดชอบด้านล่างนี้ ดำเนินงานภายใต้กรอบเดียวกันนี้</div>
      </div>

      <div class="frame-body">
        <div class="core-team">
          <div class="core-card leader">
            <span class="core-avatar">อม</span>
            <div><div class="core-role">Leader</div><div class="core-name">คุณอมร</div></div>
          </div>
          <div class="core-card advisor">
            <span class="core-avatar">ยู้</span>
            <div><div class="core-role">Advisor</div><div class="core-name">คุณยู้</div></div>
          </div>
          <div class="core-card manager">
            <span class="core-avatar">เฟ</span>
            <div><div class="core-role">Manager</div><div class="core-name">คุณเฟย์</div></div>
          </div>
          <div class="core-card coordinator">
            <span class="core-avatar">บอ</span>
            <div><div class="core-role">Coordinator</div><div class="core-name">คุณบอล</div></div>
          </div>
        </div>

        <section class="summary">
          <div class="stat"><div class="stat-label">DEPARTMENTS</div><div id="deptCount" class="stat-value">0</div></div>
          <div class="stat"><div class="stat-label">RESPONSIBILITIES</div><div id="workCount" class="stat-value">0</div><div id="workSub" class="stat-sub"></div></div>
          <div class="stat"><div class="stat-label">OWNERS</div><div id="ownerCount" class="stat-value">0</div><div id="ownerSub" class="stat-sub"></div></div>
        </section>

        <div class="legend">
          <div class="legend-item"><span class="legend-dot person"></span> ผู้รับผิดชอบ (บุคคล)</div>
          <div class="legend-item"><span class="legend-dot advisor"></span> ที่ปรึกษา / พาร์ทเนอร์</div>
          <div class="legend-item"><span class="legend-dot team"></span> หน่วยงาน / ทีม (ไม่ใช่บุคคล)</div>
          <div class="legend-item"><span class="legend-dot vacant"></span> ว่าง (ยังไม่มีผู้รับผิดชอบ)</div>
        </div>

        <section class="board">
          <div class="board-head">
            <div class="dept-head">Department</div>
            <div class="work-head">Responsibilities &amp; Owners</div>
          </div>
          <div class="board-scroll">
            <div id="rows" class="rows"></div>
          </div>
        </section>
      </div>
    </section>
  </div>
</div>

<script>
const DATA = __DATA__;
const STAMP = "__STAMP__";

const OWNER_TYPES = {
  "คุณ พิชิต":"advisor","คุณพิชิต":"advisor","อาจารย์พิชิต(คุณ third)":"advisor",
  "คุณ ตัน":"advisor","คุณตัน":"advisor","อาจารย์ตัน(คุณเก่ง)":"advisor",
  "ztt(pem-คุณเอก/psl-คุณเฟย์)":"partner","lab":"team",
  "มูลนิธิพัฒนาทุนทางปัญญาชุมชนสุวรรณภูมิ":"team","คณะ mm":"team","คณะmm":"team","ว่าง":"vacant"
};
function ownerType(o){ return OWNER_TYPES[(o||"").trim().replace(/\\s+/g," ").toLowerCase()] || ""; }
function initials(n){ return n.replace(/^(คุณ|อาจารย์)\\s*/,"").trim().slice(0,2).toUpperCase(); }
function escapeHtml(s){
  return String(s).replace(/[&<>"']/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
}
function tintBg(hex){
  const h = hex.replace("#","");
  if(h.length !== 6) return "#fff";
  const r=parseInt(h.slice(0,2),16),g=parseInt(h.slice(2,4),16),b=parseInt(h.slice(4,6),16);
  return `rgba(${r},${g},${b},0.07)`;
}

const VACANT_WORDS = ["ว่าง","vacant","-",""];
function ownerKey(n){ return String(n||"").replace(/\\s+/g,"").toLowerCase(); }
function isVacant(n){ return VACANT_WORDS.includes(ownerKey(n)); }
function ownerStats(items){
  const groups = new Map(); let vacant = 0;
  items.forEach(it=>{
    if(isVacant(it.owner)){ vacant++; return; }
    const k = ownerKey(it.owner);
    if(!groups.has(k)) groups.set(k, new Set());
    groups.get(k).add(String(it.owner).trim());
  });
  const merged = [];
  groups.forEach(s=>{ if(s.size>1) merged.push([...s]); });
  return { count: groups.size, vacant, merged };
}

function issuesHtml(list){
  if(!list || !list.length) return "";
  return `<div class="issue-list-card">` + list.map(i=>
    `<div class="issue-mini ${escapeHtml(i.severity)}"><span class="dot">⬤</span><span>${escapeHtml(i.title)}</span></div>`
  ).join("") + `</div>`;
}

function render(){
  const q = document.getElementById("search").value.trim().toLowerCase();
  const rows = document.getElementById("rows");
  rows.innerHTML = "";

  DATA.forEach(dept=>{
    const visible = dept.items.filter(x =>
      !q || x.name.toLowerCase().includes(q) || x.owner.toLowerCase().includes(q)
        || (x.scope||"").toLowerCase().includes(q)
        || (x.out_of_scope||"").toLowerCase().includes(q)
        || (x.kpi||"").toLowerCase().includes(q));

    const row = document.createElement("div");
    row.className = "row";
    const d = document.createElement("div");
    d.className = "dept";
    d.innerHTML = `<div class="dept-name">${escapeHtml(dept.name)}</div>
                   <div class="dept-count">${dept.items.length} responsibilities</div>`;
    row.appendChild(d);

    const area = document.createElement("div");
    area.className = "work-area";

    if(visible.length===0 && q){
      area.innerHTML = `<div class="empty">ไม่พบรายการที่ตรงกับการค้นหา</div>`;
    } else {
      visible.forEach(item=>{
        const type = ownerType(item.owner);
        const card = document.createElement("div");
        card.className = "card" + (type ? " " + type : "") + (item.color ? " tinted" : "");
        if(item.color){
          card.style.borderLeftColor = item.color;
          card.style.background = tintBg(item.color);
        }
        card.innerHTML = `
          <div class="card-title">${escapeHtml(item.name)}</div>
          ${(item.scope || item.out_of_scope) ? `
          <div class="scope-box">
            ${item.scope ? `<div class="scope-line do"><span class="mk">✅</span><span class="tx" title="ทำ: ${escapeHtml(item.scope)}">${escapeHtml(item.scope)}</span></div>` : ""}
            ${item.out_of_scope ? `<div class="scope-line dont"><span class="mk">❌</span><span class="tx" title="ไม่ทำ: ${escapeHtml(item.out_of_scope)}">${escapeHtml(item.out_of_scope)}</span></div>` : ""}
          </div>` : `<div class="scope-empty">ยังไม่ได้ระบุขอบเขตงาน</div>`}
          ${item.kpi
            ? `<div class="kpi-line"><span class="mk kpi-badge">KPI</span><span class="tx" title="KPI: ${escapeHtml(item.kpi)}">${escapeHtml(item.kpi)}</span></div>`
            : `<div class="kpi-empty">ยังไม่ได้กำหนด KPI</div>`}
          ${issuesHtml(item.issues)}
          <div class="owner">
            <span class="avatar">${escapeHtml(initials(item.owner))}</span>
            <span>${escapeHtml(item.owner)}</span>
            ${type==="advisor" ? `<span class="role-tag">ที่ปรึกษา</span>` : ""}
          </div>`;
        area.appendChild(card);
      });
    }
    row.appendChild(area);
    rows.appendChild(row);
  });

  const all = DATA.flatMap(d=>d.items);
  document.getElementById("deptCount").textContent = DATA.length;
  document.getElementById("workCount").textContent = all.length;
  const os = ownerStats(all);
  document.getElementById("ownerCount").textContent = os.count;

  const ownerSub = document.getElementById("ownerSub");
  const parts = [];
  if(os.vacant) parts.push(`+ ${os.vacant} ตำแหน่งว่าง`);
  if(os.merged.length) parts.push(`รวมชื่อซ้ำ ${os.merged.length} กลุ่ม`);
  ownerSub.textContent = parts.join(" · ");
  document.getElementById("workSub").textContent = "= จำนวนกล่องทั้งหมด";
}

function updatePrintMeta(){
  const el = document.getElementById("printMeta");
  const all = DATA.flatMap(d=>d.items);
  const os = ownerStats(all);
  el.textContent = `${DATA.length} departments · ${all.length} responsibilities · ${os.count} owners`
    + (os.vacant ? ` (+${os.vacant} ว่าง)` : "")
    + ` · ข้อมูล ณ ${STAMP} · ร่างขอบเขตงานยังไม่ผ่านการยืนยันจากที่ประชุม`;
}
window.addEventListener("beforeprint", updatePrintMeta);
function exportPDF(){ updatePrintMeta(); setTimeout(()=>window.print(), 200); }

document.getElementById("search").addEventListener("input", render);
render();
</script>
</body>
</html>
"""


def main():
    css = read_css()
    data = load_data()
    stamp = thai_stamp(datetime.now())

    out = (TEMPLATE
           .replace("__CSS__", css)
           .replace("__DATA__", json.dumps(data, ensure_ascii=False))
           .replace("__STAMP__", stamp))

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(out)

    n_items = sum(len(d["items"]) for d in data)
    n_issues = sum(len(i.get("issues", [])) for d in data for i in d["items"])
    print("")
    print("  ✓ สร้าง %s แล้ว" % OUT_PATH)
    print("    %d departments · %d responsibilities · %d ปัญหาที่ยังเปิดอยู่" %
          (len(data), n_items, n_issues))
    print("    ข้อมูล ณ %s" % stamp)
    print("")
    print("  ขั้นตอนถัดไป:  git add index.html && git commit -m \"update public map\" && git push")
    print("")


if __name__ == "__main__":
    main()
