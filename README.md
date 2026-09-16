# Countryside Responsibility Map — ระบบฐานข้อมูล SQLite

เดิมข้อมูลทั้งหมดถูก hardcode ไว้ในไฟล์ HTML แก้แล้วหายทุกครั้งที่ปิดหน้าเว็บ
ตอนนี้ข้อมูลย้ายไปอยู่ใน SQLite แล้ว **แก้แล้วบันทึกถาวร ทุกคนที่เข้ามาเห็นข้อมูลชุดเดียวกัน**

---

## ไฟล์ในชุดนี้

| ไฟล์ | หน้าที่ |
|---|---|
| `server.py` | ตัว server + ฐานข้อมูล ใช้ Python standard library ล้วน **ไม่ต้อง pip install อะไรเลย** |
| `countryside_map_db.html` | หน้าเว็บ (เวอร์ชัน V2 ที่ต่อกับ API แล้ว) |
| `seed.json` | ข้อมูลตั้งต้น 8 departments / 38 responsibilities ใช้เฉพาะครั้งแรกที่รัน |
| `countryside.db` | ฐานข้อมูลจริง — **สร้างอัตโนมัติ** ครั้งแรกที่รัน ไฟล์นี้คือข้อมูลของคุณ |

---

## วิธีรัน

ต้องมี Python 3.8 ขึ้นไป (macOS/Linux มีมาให้อยู่แล้ว · Windows ดาวน์โหลดที่ python.org)

```bash
cd โฟลเดอร์ที่เก็บไฟล์ทั้งหมด
python3 server.py
```

จะขึ้นข้อความประมาณนี้

```
  🎋 Countryside Responsibility Map — SQLite server
  --------------------------------------------------
  ✓ seed ข้อมูลตั้งต้นจาก seed.json แล้ว
  ✓ สร้างฐานข้อมูลใหม่: .../countryside.db
  ✓ ข้อมูลปัจจุบัน: 8 departments, 38 responsibilities

  เปิดเบราว์เซอร์ที่ →  http://127.0.0.1:8787
```

เปิดเบราว์เซอร์ไปที่ **http://localhost:8787**

> ⚠️ **ต้องเปิดผ่าน server เท่านั้น** ดับเบิลคลิกไฟล์ HTML ตรงๆ จะขึ้นกล่องแดงว่าเชื่อมต่อไม่ได้
> เพราะเบราว์เซอร์จะบล็อกการเรียก API จากไฟล์ `file://`

หยุด server ด้วย `Ctrl + C` — ข้อมูลถูกบันทึกไปแล้วทุกครั้งที่กด Save ไม่ต้องกดบันทึกอีก

---

## ให้คนอื่นในทีมเข้าใช้ด้วย

รันแบบเปิดรับเครื่องอื่นในวง LAN เดียวกัน

```bash
HOST=0.0.0.0 python3 server.py
```

แล้วให้เพื่อนเปิด `http://<ip-เครื่องคุณ>:8787` (หา IP ด้วย `ipconfig` หรือ `ifconfig`)

**ยังไม่มีระบบ login** ใครเข้าถึง URL ได้ก็แก้ข้อมูลได้ เหมาะกับใช้ในวง LAN ของออฟฟิศ
ถ้าจะเอาขึ้นอินเทอร์เน็ตจริง ต้องเพิ่มระบบยืนยันตัวตนก่อน

---

## โครงสร้างฐานข้อมูล

```sql
departments (
  id, name UNIQUE, sort_order, created_at, updated_at
)

responsibilities (
  id, department_id → departments.id ON DELETE CASCADE,
  name, owner, scope, sort_order, created_at, updated_at
)

audit_log (
  id, ts, action, entity, entity_id, detail
)

issues (
  id, item_id → responsibilities.id ON DELETE CASCADE,
  title, detail,
  severity  'high' | 'medium' | 'low',
  status    'open' | 'resolved',
  created_at, updated_at, resolved_at
)
```

> ลบกล่องงานทิ้ง ปัญหาที่ผูกกับกล่องนั้นจะถูกลบตามไปด้วย (CASCADE)

หมายเหตุ: คอลัมน์ `scope` มีอยู่ในฐานข้อมูลแล้ว แต่หน้าเว็บ V2 ยังไม่มีช่องกรอก
ถ้าอยากใช้ scope อีกครั้ง เพิ่ม `<textarea id="scope">` ในฟอร์มแล้วส่งค่าไปกับ API ได้เลย ฝั่ง server รองรับอยู่แล้ว

---

## API

| Method | Endpoint | ทำอะไร |
|---|---|---|
| GET | `/api/state` | ดึงข้อมูลทั้งหมด (departments + items) |
| POST | `/api/departments` | เพิ่ม department · body `{name}` |
| PUT | `/api/departments/{id}` | แก้ชื่อ department |
| DELETE | `/api/departments/{id}?moveTo={id}` | ลบ · ถ้ายังมีงานอยู่ต้องระบุ `moveTo` |
| POST | `/api/items` | เพิ่ม responsibility · body `{department_id, name, owner, scope}` |
| PUT | `/api/items/{id}` | แก้ไข / ย้าย department |
| DELETE | `/api/items/{id}` | ลบ |
| GET | `/api/issues` | ปัญหาทั้งระบบ (พร้อมชื่อ department / กล่องงาน / owner + สรุปจำนวน) |
| GET | `/api/issues?item_id={id}` | ปัญหาเฉพาะกล่องเดียว |
| POST | `/api/issues` | แจ้งปัญหา · body `{item_id, title, detail, severity}` |
| PUT | `/api/issues/{id}` | แก้ไข หรือปิด/เปิดปัญหา · body `{title, detail, severity, status}` |
| DELETE | `/api/issues/{id}` | ลบปัญหา |
| GET | `/api/history?limit=80` | ประวัติการแก้ไข |
| GET | `/api/export.csv` | ดาวน์โหลด CSV (มี BOM เปิดใน Excel ภาษาไทยไม่เพี้ยน) |
| GET | `/api/backup.db` | ดาวน์โหลดไฟล์ฐานข้อมูลสำรอง |

ทุก endpoint ที่เปลี่ยนข้อมูลจะคืน `state` ชุดใหม่กลับมาด้วย หน้าเว็บจึงไม่ต้องยิงซ้ำ

---

## ปัญหาที่พบ (Issues)

- **คลิกที่การ์ดใดก็ได้** → เปิดหน้าปัญหาของกล่องนั้น กรอก *หัวข้อ · รายละเอียด · ความรุนแรง (🔴 สูง / 🟠 กลาง / 🔵 ต่ำ)*
  แล้วกด **บันทึกปัญหา** · หนึ่งกล่องมีปัญหาได้หลายรายการ
- ในรายการแต่ละบรรทัดมีปุ่ม **✔ แก้แล้ว** (กด ↺ เพื่อเปิดใหม่) · **✎ แก้ไข** · **🗑 ลบ**
- มุมล่างขวาของการ์ดจะมีป้าย **⚠ n** บอกจำนวนปัญหาที่ยังไม่แก้ สีตามความรุนแรงสูงสุด
  การ์ดที่ยังไม่มีปัญหาจะขึ้น **＋ ปัญหา** จางๆ ไว้ให้กดแจ้ง
- ปุ่ม **⚠ Issues** บนหัวเรื่อง = หน้ารวมปัญหาทั้งระบบ กรองตาม department / ความรุนแรง / สถานะ
  และค้นหาข้อความได้ · กดชื่อกล่องในรายการเพื่อกระโดดกลับไปที่กล่องนั้น
- ตัวเลขบนปุ่ม ⚠ Issues = จำนวนปัญหาที่ยังเปิดอยู่ทั้งระบบ
- การลาก-วางการ์ดยังทำงานเหมือนเดิม ระบบแยกการลากออกจากการคลิกให้แล้ว

---

## ปุ่มใหม่บนหน้าเว็บ

- **⚠ Issues** — หน้ารวมปัญหาทั้งระบบ พร้อมตัวเลขปัญหาที่ยังไม่แก้
- **🕘 History** — ดูว่าใครแก้อะไรไปบ้าง เรียงจากล่าสุด
- **⤓ CSV** — โหลดตารางไปทำต่อใน Excel
- **⛁ Backup** — โหลดไฟล์ `.db` เก็บไว้ ตั้งชื่อตามวันที่ให้อัตโนมัติ
- จุดสถานะข้างหัวเรื่อง เขียว = ต่อฐานข้อมูลอยู่ · แดง = หลุด

---

## เว็บสาธารณะ + เก็บข้อมูลจากทีม (GitHub Pages)

ชุดนี้ให้ทุกคนเปิดเว็บ แก้ข้อมูลของตัวเอง แล้วส่งไฟล์กลับมารวม โดยไม่ต้องมี server

| ไฟล์ | หน้าที่ |
|---|---|
| `data.json` | ข้อมูลทั้งหมดในรูปแบบ JSON — หน้าเว็บอ่านไฟล์นี้ |
| `index.html` | หน้าเว็บสาธารณะ อ่าน `data.json` มาแสดง และให้แก้ไขในเครื่องตัวเองได้ |
| `_template.html` | ต้นแบบของ `index.html` (แก้ดีไซน์/ข้อความหน้าสาธารณะที่ไฟล์นี้) |
| `build_static.py` | สร้าง `data.json` + `index.html` จาก `countryside.db` |
| `merge_submissions.py` | รวมไฟล์ที่แต่ละคนส่งกลับ เข้า `countryside.db` |

### วงจรการทำงาน

```
countryside.db ──build_static.py──▶ data.json + index.html ──git push──▶ GitHub Pages
                                                                            │
                        แต่ละคนเปิดเว็บ แก้ของตัวเอง กดดาวน์โหลด data-ชื่อ.json
                                                                            │
countryside.db ◀──merge_submissions.py── ไฟล์ที่ทุกคนส่งกลับ ◀────────────────┘
```

### 1. สร้างและอัปเดตเว็บ

```bash
python build_static.py
git add index.html data.json
git commit -m "update public map"
git push
```

`build_static.py` ดึง CSS จาก `countryside_map_db.html` ให้เอง หน้าสาธารณะจึงหน้าตาเหมือนหน้าเว็บตัวเต็มเสมอ

**เปิด GitHub Pages ครั้งแรก:** repo บน GitHub → **Settings › Pages** →
Source = **Deploy from a branch** → Branch **main** / **/(root)** → Save
ได้ลิงก์ `https://<username>.github.io/<repo>/`

### 2. แต่ละคนแก้ข้อมูลของตัวเอง

เปิดลิงก์ → ใส่ชื่อตัวเอง → กด **เฉพาะงานของฉัน** → คลิกการ์ดเพื่อแก้
Scope / Out of Scope / KPI และเพิ่มปัญหาที่พบ → กด **⬇ ดาวน์โหลด data.json** → ส่งไฟล์ให้ผู้ประสานงาน

สิ่งที่แก้เก็บไว้ใน localStorage ของเบราว์เซอร์คนนั้นเอง ปิดหน้าแล้วเปิดใหม่ข้อมูลยังอยู่
คนอื่นไม่เห็นจนกว่าจะรวมไฟล์เข้าระบบ — จึงแก้ได้ทีละคน ไม่ทับกัน

### 3. รวมไฟล์ที่ส่งกลับ

```bash
python merge_submissions.py --dry-run data-*.json   # ดูก่อนว่าจะเปลี่ยนอะไร
python merge_submissions.py data-*.json             # เขียนจริง
python merge_submissions.py submissions/            # ทั้งโฟลเดอร์
```

- แตะเฉพาะกล่องที่คนนั้น**แก้จริง** (หน้าเว็บติดธง `edited` ไว้) กล่องอื่นในไฟล์เดียวกันไม่ถูกเขียนทับ
- ปัญหาใหม่ถูกเพิ่มเข้าตาราง `issues` · ปัญหาหัวข้อซ้ำถือเป็นตัวเดียวกัน รวมไฟล์เดิมซ้ำสองรอบก็ไม่เกิดข้อมูลซ้ำ
- ทุกการเปลี่ยนแปลงบันทึกลง `audit_log` พร้อมชื่อผู้ส่ง ดูย้อนหลังได้ที่ปุ่ม 🕘 History
- เสร็จแล้วรัน `build_static.py` + push อีกครั้ง เพื่อให้เว็บสาธารณะตรงกับข้อมูลล่าสุด

> ⚠️ GitHub Pages บน repo แบบ public = ใครมีลิงก์ก็เปิดได้ และหน้านี้มีชื่อทีมกับขอบเขตงานภายใน
> ถ้าไม่ต้องการให้เปิดสาธารณะ อย่าเปิด Pages บน repo public

---

## การสำรองข้อมูล

ข้อมูลทั้งหมดอยู่ในไฟล์เดียวคือ `countryside.db` ก๊อปปี้ไฟล์นี้เก็บไว้ = สำรองเสร็จ

```bash
cp countryside.db backup_$(date +%Y%m%d).db
```

หรือกดปุ่ม **⛁ Backup** บนหน้าเว็บ

> จะมีไฟล์ `countryside.db-wal` และ `-shm` โผล่มาด้วย เป็นไฟล์ชั่วคราวของ SQLite ปกติ
> ถ้าจะก๊อปปี้ตอน server ยังรันอยู่ ให้ใช้ปุ่ม Backup แทน จะได้ข้อมูลครบกว่า

---

## เริ่มข้อมูลใหม่ทั้งหมด

ลบ `countryside.db` แล้วรัน server ใหม่ ระบบจะ seed จาก `seed.json` ให้อีกครั้ง
ถ้าอยากเปลี่ยนข้อมูลตั้งต้น แก้ `seed.json` ก่อนลบ

---

## ปัญหาที่เจอบ่อย

| อาการ | สาเหตุ / วิธีแก้ |
|---|---|
| กล่องแดง "เชื่อมต่อฐานข้อมูลไม่ได้" | ยังไม่ได้รัน `server.py` หรือเปิดไฟล์ HTML ตรงๆ ไม่ผ่าน localhost |
| `Address already in use` | พอร์ต 8787 ถูกใช้อยู่ · รันด้วย `PORT=9000 python3 server.py` |
| `python3: command not found` | Windows ให้ใช้ `python server.py` แทน |
| แก้แล้วเพื่อนไม่เห็น | ให้เพื่อนกด refresh · ระบบยังไม่มี real-time sync |
