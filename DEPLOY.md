# Deploy Production — Docker

ชุดนี้ประกอบด้วย 3 services

| Service | ทำอะไร |
|---|---|
| **app** | ตัวแอป + SQLite ไม่เปิดพอร์ตออกภายนอกเลย เข้าถึงได้ผ่าน caddy เท่านั้น |
| **caddy** | Reverse proxy · ทำ HTTPS อัตโนมัติ · **Basic Auth** (ด่านป้องกันเดียวของระบบ) |
| **backup** | สำรองฐานข้อมูลอัตโนมัติทุกวัน เก็บย้อนหลัง 30 วัน |

---

## ⚠️ อ่านก่อน: ข้อจำกัดที่ต้องยอมรับ

**1. แอปยังไม่มีระบบ login ของตัวเอง**
ความปลอดภัยทั้งหมดอยู่ที่ Basic Auth ชั้น Caddy ทุกคนที่ผ่านเข้ามาได้จะมีสิทธิ์เท่ากันหมด
แก้ได้ ลบได้ ไม่มีการแยกสิทธิ์ผู้ใช้ และ audit log บันทึกได้แค่ว่า "มีการแก้อะไร" ไม่รู้ว่า "ใครแก้"
ถ้าต้องการแยกผู้ใช้จริงๆ ต้องเพิ่มระบบ authentication ในแอปก่อน

**2. server ใช้ `http.server` ของ Python**
รองรับผู้ใช้พร้อมกันได้ระดับหลายสิบคน เพียงพอสำหรับทีมภายใน
แต่ไม่ได้ออกแบบมารับ traffic สาธารณะจำนวนมาก ถ้าโตกว่านี้ควรย้ายไป FastAPI + uvicorn
โครงสร้าง API เดิมย้ายได้ไม่ยาก เพราะแยก handler ไว้เป็นฟังก์ชันอยู่แล้ว

**3. SQLite เขียนได้ทีละคน**
เหมาะกับงานแบบนี้ที่อ่านเยอะเขียนน้อย แต่ scale แนวนอนไม่ได้
**ห้ามรัน app มากกว่า 1 replica** เด็ดขาด จะทำให้ฐานข้อมูลเสียหาย

---

## ขั้นตอน deploy

### 1. เตรียมไฟล์บนเครื่อง server

```bash
git clone <repo> countryside-map   # หรืออัปโหลดโฟลเดอร์ขึ้นไป
cd countryside-map
```

ต้องมีไฟล์ครบตามนี้

```
Dockerfile  docker-compose.yml  Caddyfile  .env.example
server.py   backup.py  seed.json  countryside_map_db.html
```

### 2. สร้างรหัสผ่าน

```bash
docker run --rm caddy:2.8-alpine caddy hash-password --plaintext 'รหัสผ่านที่ต้องการ'
```

จะได้ hash ขึ้นต้นด้วย `$2a$14$...` คัดลอกไว้

### 3. ตั้งค่า .env

```bash
cp .env.example .env
nano .env
```

```ini
SITE_ADDRESS=map.yourdomain.com
BASIC_AUTH_USER=countryside
BASIC_AUTH_HASH=$$2a$$14$$xxxxxxxxxxxxxxxxxxxxx
BACKUP_KEEP_DAYS=30
TZ=Asia/Bangkok
```

> **สำคัญ:** เครื่องหมาย `$` ในไฟล์ `.env` ต้องพิมพ์เป็น `$$` ทุกตัว
> ไม่งั้น docker compose จะตีความเป็นตัวแปรแล้วรหัสผ่านจะใช้ไม่ได้

### 4. เตรียมโฟลเดอร์สำรองข้อมูล

container รันด้วย uid `10001` จึงต้องให้สิทธิ์เขียนก่อน

```bash
mkdir -p backups
sudo chown 10001:10001 backups
```

### 5. ชี้ DNS

สร้าง A record ของ `map.yourdomain.com` ชี้มาที่ IP ของ server
**ต้องทำก่อนขั้นถัดไป** ไม่งั้น Caddy ขอใบรับรอง HTTPS ไม่สำเร็จ

### 6. เปิดพอร์ตบน firewall

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
```

### 7. รัน

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f
```

เปิด `https://map.yourdomain.com` ใส่ user/password ที่ตั้งไว้ เสร็จ

---

## ใช้ในวง LAN (ไม่มีโดเมน)

แก้ `.env` เป็น

```ini
SITE_ADDRESS=:80
```

แล้วเข้าที่ `http://<ip-server>` — จะเป็น HTTP ธรรมดา ไม่มีการเข้ารหัส
**ห้ามใช้แบบนี้บนอินเทอร์เน็ตสาธารณะ** เพราะรหัสผ่าน Basic Auth จะวิ่งเป็น plain text

---

## คำสั่งที่ใช้บ่อย

```bash
docker compose logs -f app          # ดู log แอป
docker compose logs -f backup       # ดู log การสำรองข้อมูล
docker compose restart app          # รีสตาร์ท
docker compose down                 # หยุด (ข้อมูลยังอยู่ใน volume)
docker compose up -d --build        # อัปเดตโค้ดแล้ว deploy ใหม่
docker compose exec app python3 -c "print('ok')"
```

### เช็คสุขภาพระบบ

```bash
docker compose ps                   # ดูคอลัมน์ STATUS ต้องขึ้น (healthy)
curl -u user:pass https://map.yourdomain.com/api/health
```

---

## การสำรองและกู้คืน

### สำรอง

service `backup` ทำให้อัตโนมัติทุก 24 ชั่วโมง ไฟล์อยู่ในโฟลเดอร์ `./backups/`
ใช้ SQLite backup API จึงปลอดภัยแม้มีคนใช้งานอยู่ (ต่างจากการ `cp` เฉยๆ ที่อาจได้ไฟล์เสีย)

สำรองทันทีแบบ manual

```bash
docker compose exec backup python3 -c "import backup; backup.make_backup()"
```

หรือกดปุ่ม **⛁ Backup** บนหน้าเว็บ

### กู้คืน

```bash
docker compose stop app backup
docker run --rm -v countryside-map_app-data:/data -v $(pwd)/backups:/b alpine \
  cp /b/countryside_20260902_0300.db /data/countryside.db
docker compose start app backup
```

### ย้ายเครื่อง

ก๊อปโฟลเดอร์โปรเจกต์ + ไฟล์ `.db` ล่าสุด ไปวางที่เครื่องใหม่ แล้ว

```bash
docker compose up -d --build
docker compose stop app
docker run --rm -v countryside-map_app-data:/data -v $(pwd):/b alpine \
  cp /b/countryside.db /data/countryside.db
docker compose start app
```

---

## แก้ปัญหา

| อาการ | สาเหตุ / วิธีแก้ |
|---|---|
| Caddy ขอ certificate ไม่ผ่าน | DNS ยังไม่ชี้มาที่เครื่องนี้ · หรือพอร์ต 80/443 ถูกบล็อก · ดู `docker compose logs caddy` |
| ใส่รหัสผ่านถูกแต่เข้าไม่ได้ | ลืมเปลี่ยน `$` เป็น `$$` ใน `.env` |
| backup ขึ้น Permission denied | ยังไม่ได้ `sudo chown 10001:10001 backups` |
| app ขึ้น `unhealthy` | `docker compose logs app` · มักเป็นเพราะ volume `/data` เขียนไม่ได้ |
| `port is already allocated` | มี nginx/apache ใช้พอร์ต 80 อยู่ · หยุดตัวนั้นก่อน หรือเปลี่ยน port mapping ของ caddy |
| ข้อมูลหายหลัง `docker compose down -v` | flag `-v` ลบ volume ทิ้ง **อย่าใช้** ถ้าไม่ได้ตั้งใจล้างข้อมูล |

---

## สิ่งที่ควรทำเพิ่มถ้าใช้งานจริงจัง

- [ ] เพิ่มระบบ login ในแอป เพื่อให้ audit log รู้ว่าใครแก้
- [ ] ตั้ง cron ก๊อปโฟลเดอร์ `backups/` ขึ้น cloud storage — สำรองไว้ในเครื่องเดียวกันไม่รอดถ้าดิสก์พัง
- [ ] ทดสอบกู้คืนจริงสักครั้ง ไฟล์สำรองที่ไม่เคยทดสอบกู้ = ไม่นับว่ามีไฟล์สำรอง
- [ ] ตั้ง monitoring ยิง `/api/health` เช่น UptimeRobot หรือ Healthchecks.io
