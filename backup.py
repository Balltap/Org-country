#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
สำรองฐานข้อมูลอัตโนมัติ — รันเป็น service แยกใน docker-compose

ใช้ sqlite3 backup API (ไม่ใช่ cp) จึงปลอดภัยแม้ server กำลังเขียนข้อมูลอยู่
ไฟล์เก่ากว่า BACKUP_KEEP_DAYS จะถูกลบทิ้งอัตโนมัติ

ตัวแปรที่ปรับได้:
  DATA_DIR                โฟลเดอร์ฐานข้อมูล            (default /data)
  BACKUP_DIR              โฟลเดอร์เก็บไฟล์สำรอง        (default /backups)
  BACKUP_INTERVAL_HOURS   สำรองทุกกี่ชั่วโมง            (default 24)
  BACKUP_KEEP_DAYS        เก็บย้อนหลังกี่วัน             (default 30)
"""

import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta

DATA_DIR = os.environ.get("DATA_DIR", "/data")
BACKUP_DIR = os.environ.get("BACKUP_DIR", "/backups")
DB_PATH = os.path.join(DATA_DIR, "countryside.db")
INTERVAL_H = float(os.environ.get("BACKUP_INTERVAL_HOURS", "24"))
KEEP_DAYS = int(os.environ.get("BACKUP_KEEP_DAYS", "30"))


def log(msg):
    print("[backup %s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg), flush=True)


def make_backup():
    if not os.path.exists(DB_PATH):
        log("ยังไม่มีไฟล์ฐานข้อมูล ข้ามรอบนี้")
        return None

    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    target = os.path.join(BACKUP_DIR, "countryside_%s.db" % stamp)

    # ต้องเปิดแบบ read-write เพราะโหมด WAL ต้องเขียนไฟล์ -shm ได้แม้ตอนอ่าน
    src = sqlite3.connect(DB_PATH, timeout=30)
    dst = sqlite3.connect(target)
    try:
        # backup API อ่านแบบ consistent snapshot ปลอดภัยกว่าการ copy ไฟล์ตรงๆ
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    size_kb = os.path.getsize(target) / 1024
    log("สำรองสำเร็จ: %s (%.1f KB)" % (os.path.basename(target), size_kb))
    return target


def prune():
    if not os.path.isdir(BACKUP_DIR):
        return
    cutoff = time.time() - KEEP_DAYS * 86400
    removed = 0
    for name in os.listdir(BACKUP_DIR):
        if not (name.startswith("countryside_") and name.endswith(".db")):
            continue
        path = os.path.join(BACKUP_DIR, name)
        if os.path.getmtime(path) < cutoff:
            os.remove(path)
            removed += 1
    if removed:
        log("ลบไฟล์สำรองที่เก่ากว่า %d วัน จำนวน %d ไฟล์" % (KEEP_DAYS, removed))


def main():
    log("เริ่มทำงาน — สำรองทุก %g ชั่วโมง เก็บย้อนหลัง %d วัน" % (INTERVAL_H, KEEP_DAYS))
    log("ต้นทาง: %s → ปลายทาง: %s" % (DB_PATH, BACKUP_DIR))

    # รอให้ server สร้างฐานข้อมูลเสร็จก่อนรอบแรก
    time.sleep(20)

    while True:
        try:
            make_backup()
            prune()
        except Exception as e:
            log("ผิดพลาด: %s" % e)
        next_run = datetime.now() + timedelta(hours=INTERVAL_H)
        log("รอบถัดไป: %s" % next_run.strftime("%Y-%m-%d %H:%M"))
        time.sleep(INTERVAL_H * 3600)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("หยุดการทำงาน")
        sys.exit(0)
