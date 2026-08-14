import os
import json
import time
import logging
from datetime import datetime
from collections import defaultdict
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv
import httpx

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
FRONTEND_DOMAIN = os.getenv("FRONTEND_DOMAIN", "*")
PORT = int(os.getenv("PORT", "8000"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Fediv Bus API", version="2.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_DOMAIN] if FRONTEND_DOMAIN != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type"],
)

# Rate limiter
rate_limit = defaultdict(list)
RATE_LIMIT = 5
RATE_WINDOW = 60

def check_rate_limit(ip: str) -> bool:
    now = time.time()
    rate_limit[ip] = [t for t in rate_limit[ip] if now - t < RATE_WINDOW]
    if len(rate_limit[ip]) >= RATE_LIMIT:
        return False
    rate_limit[ip].append(now)
    return True

DATA_FILE = "submissions.json"

def save_submission(data: dict) -> str:
    submissions = []
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                submissions = json.load(f)
        except:
            pass
    sid = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(submissions)}"
    entry = {"id": sid, "timestamp": datetime.now().isoformat(), **data}
    submissions.append(entry)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(submissions, f, ensure_ascii=False, indent=2)
    return sid

async def send_telegram_message(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set!")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            r = await client.post(url, json=payload)
            result = r.json()
            if not result.get("ok"):
                logger.error(f"Telegram API error: {result}")
            return result.get("ok", False)
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            return False

@app.on_event("startup")
async def startup():
    logger.info(f"=== STARTUP ===")
    logger.info(f"TOKEN set: {bool(TELEGRAM_BOT_TOKEN)}")
    logger.info(f"CHAT_ID set: {bool(TELEGRAM_CHAT_ID)}")
    logger.info(f"CHAT_ID value: {TELEGRAM_CHAT_ID}")
    logger.info(f"FRONTEND_DOMAIN: {FRONTEND_DOMAIN}")

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "telegram": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID),
        "token_set": bool(TELEGRAM_BOT_TOKEN),
        "chat_id_set": bool(TELEGRAM_CHAT_ID)
    }

@app.post("/api/submit")
async def submit_form(data: dict, request: Request):
    client_ip = request.client.host
    logger.info(f"Submit from {client_ip}: {data}")

    if not check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Too many requests")

    service = data.get("service")
    name = data.get("name", "").strip()
    phone = data.get("phone", "").strip()

    if not name or not phone:
        raise HTTPException(status_code=400, detail="Required fields missing")
    if len(name) < 2 or len(phone) < 5:
        raise HTTPException(status_code=400, detail="Invalid data")

    sid = save_submission(data)
    logger.info(f"[{client_ip}] New submission #{sid}: {service} — {name}")

    ts = datetime.now().strftime("%d.%m.%Y, %H:%M")

    if service == "permis":
        status = data.get("status", "—")
        msg = (
            f"📋 <b>НОВА ЗАЯВКА — Румунський перміс</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Ім'я:</b> {name}\n"
            f"📱 <b>Тел:</b> {phone}\n"
            f"🏷 <b>Статус:</b> {status}\n"
            f"🕐 <b>Час:</b> {ts}\n"
            f"🌐 <b>IP:</b> {client_ip}\n"
            f"🆔 <b>ID:</b> {sid}"
        )
    elif service == "bus":
        route = data.get("route", "—")
        msg = (
            f"🚐 <b>НОВА ЗАЯВКА — Перевезення</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Ім'я:</b> {name}\n"
            f"📱 <b>Тел:</b> {phone}\n"
            f"🛣 <b>Маршрут:</b> {route}\n"
            f"🕐 <b>Час:</b> {ts}\n"
            f"🌐 <b>IP:</b> {client_ip}\n"
            f"🆔 <b>ID:</b> {sid}"
        )
    else:
        msg = (
            f"📨 <b>НОВА ЗАЯВКА</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Ім'я:</b> {name}\n"
            f"📱 <b>Тел:</b> {phone}\n"
            f"🕐 <b>Час:</b> {ts}\n"
            f"🌐 <b>IP:</b> {client_ip}\n"
            f"🆔 <b>ID:</b> {sid}"
        )

    sent = await send_telegram_message(msg)
    logger.info(f"Telegram sent: {sent}")
    return {"success": True, "telegram": sent, "id": sid}

@app.get("/api/submissions")
async def get_submissions():
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

# Serve static HTML files (MUST be after API routes)
app.mount("/", StaticFiles(directory="site", html=True), name="site")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
