# syntax=docker/dockerfile:1
FROM python:3.12-slim

# ไม่มี dependency ภายนอกเลย — ใช้ Python standard library ล้วน
# จึงไม่ต้องมีขั้น pip install ทำให้ image เล็กและ build เร็ว

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data \
    HOST=0.0.0.0 \
    PORT=8787 \
    TZ=Asia/Bangkok

WORKDIR /app

COPY server.py backup.py seed.json countryside_map_db.html ./

# รันด้วย user ธรรมดา ไม่ใช่ root
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data /backups \
    && chown -R app:app /app /data /backups

USER app

VOLUME ["/data"]
EXPOSE 8787

# ใช้ /api/health ที่ query ฐานข้อมูลจริง ไม่ใช่แค่เช็คว่าพอร์ตเปิด
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request,sys; \
        r=urllib.request.urlopen('http://127.0.0.1:8787/api/health',timeout=3); \
        sys.exit(0 if r.status==200 else 1)"

CMD ["python3", "server.py"]
