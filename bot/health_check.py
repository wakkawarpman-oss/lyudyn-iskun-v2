import asyncio
import aiohttp
import os
import shutil
from datetime import datetime, timedelta
from aiogram import Bot
import redis
from database.models import SessionLocal, DetectedEvent

class HealthMonitor:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.alert_cooldown = {}
        self.admin_id = os.getenv("ADMIN_ID", "8965828778")
        self.redis_client = redis.Redis(host=os.getenv("REDIS_HOST", "redis"), port=6379, db=0, decode_responses=True)

    async def run(self):
        while True:
            await asyncio.sleep(300)
            
            issues = []
            now = datetime.utcnow()
            
            # Check Telethon ping from Redis
            try:
                last_ping_str = self.redis_client.get("telethon_last_ping")
                if last_ping_str:
                    last_ping = datetime.fromisoformat(last_ping_str)
                    if now - last_ping > timedelta(minutes=15):
                        issues.append("❌ Telethon не пінгує >15 хв")
                else:
                    issues.append("❌ Немає даних від Telethon")
            except Exception as e:
                issues.append(f"⚠️ Помилка перевірки Redis: {e}")
            
            # Check DB write
            try:
                db = SessionLocal()
                last_event = db.query(DetectedEvent).order_by(DetectedEvent.detected_at.desc()).first()
                db.close()
                if last_event and last_event.detected_at:
                    if now - last_event.detected_at > timedelta(hours=2):
                        issues.append("⚠️ БД не отримує подій >2 годин (можливо, просто тихо)")
            except Exception as e:
                issues.append(f"❌ Помилка БД: {e}")
            
            # Check Groq API
            groq_key = os.getenv("GROQ_API_KEY")
            if groq_key:
                try:
                    async with aiohttp.ClientSession() as s:
                        async with s.get("https://api.groq.com/openai/v1/models",
                                        headers={"Authorization": f"Bearer {groq_key}"},
                                        timeout=10) as r:
                            if r.status != 200:
                                issues.append(f"⚠️ Groq API статус {r.status}")
                except Exception as e:
                    issues.append(f"⚠️ Groq API недоступний: {e}")
            
            # Check Disk
            total, used, free = shutil.disk_usage("/")
            if total > 0 and free / total < 0.1:
                issues.append(f"🚨 Диск заповнено на {used/total*100:.0f}%")
            
            if issues:
                await self._alert_admin(issues)

    async def _alert_admin(self, issues: list):
        key = tuple(issues)
        last_alert = self.alert_cooldown.get(key)
        now = datetime.utcnow()
        if last_alert and now - last_alert < timedelta(minutes=60):
            return
        
        text = "🚨 *АЛЕРТ ЗДОРОВ'Я ОКІНТ-ПРО*\n\n" + "\n".join(issues)
        text += f"\n\n⏰ {now.strftime('%H:%M')} UTC"
        
        try:
            await self.bot.send_message(self.admin_id, text, parse_mode="Markdown")
            self.alert_cooldown[key] = now
        except Exception as e:
            print(f"Health alert failed: {e}")
