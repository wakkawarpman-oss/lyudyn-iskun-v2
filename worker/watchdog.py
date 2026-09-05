import os
import requests
import redis
import logging
from datetime import datetime, timedelta
from database.models import SessionLocal, DetectedEvent

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID", "8965828778")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

def send_alert(message: str):
    if not BOT_TOKEN or not ADMIN_ID:
        logger.warning("Watchdog: BOT_TOKEN or ADMIN_ID missing. Cannot send alert.")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": ADMIN_ID, "text": f"🚨 **WATCHDOG ALERT** 🚨\n\n{message}", "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        logger.error(f"Watchdog failed to send alert: {e}")

def run_health_check():
    logger.info("Running Watchdog health check...")
    alerts = []
    
    # 1. Check Redis Queue Size
    try:
        r = redis.Redis.from_url(REDIS_URL)
        queue_len = r.llen("celery") # default queue name
        if queue_len > 100:
            alerts.append(f"🔴 **Redis Queue Overload!**\nУ черзі застрягло {queue_len} повідомлень. Можливо Celery-воркери зависли.")
    except Exception as e:
        alerts.append(f"🔴 **Redis Connection Failed!**\nПомилка: {str(e)}")

    # 2. Check Database Liveness & Freshness
    db = SessionLocal()
    try:
        latest_event = db.query(DetectedEvent).order_by(DetectedEvent.detected_at.desc()).first()
        if latest_event:
            time_diff = datetime.utcnow() - latest_event.detected_at
            if time_diff > timedelta(hours=3):
                alerts.append(f"🟡 **No Fresh Data!**\nОстання подія в БД була {time_diff.total_seconds() // 3600} годин тому. Можливо Listener впав або Telegram дав бан!")
    except Exception as e:
        alerts.append(f"🔴 **Database Connection Failed!**\nПомилка: {str(e)}")
    finally:
        db.close()
        
    # 3. Auto-sync active dashboard URL to Redis
    try:
        tunnel_url = os.getenv("DASHBOARD_URL", "http://136.113.156.17")
        r = redis.Redis.from_url(REDIS_URL)
        r.set("active_tunnel_url", tunnel_url)
    except Exception as te:
        logger.warning(f"Watchdog tunnel sync error: {te}")

    if alerts:
        send_alert("\n\n".join(alerts))
        logger.warning("Watchdog found issues and sent an alert.")
    else:
        logger.info("Watchdog: System is healthy.")

if __name__ == "__main__":
    run_health_check()
