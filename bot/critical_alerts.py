import asyncio
from datetime import datetime, timedelta
from database.models import SessionLocal, DetectedEvent
from aiogram import Bot
import os

class CriticalAlertSystem:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.sent_alerts = set()
        self.admin_id = os.getenv("ADMIN_ID", "SECURITY_OFFICER_1")

    async def run(self):
        while True:
            await asyncio.sleep(60) # Check every minute
            await self.check_and_alert()

    async def check_and_alert(self):
        db = SessionLocal()
        try:
            since = datetime.utcnow() - timedelta(minutes=5)
            
            critical_events = db.query(DetectedEvent).filter(
                DetectedEvent.detected_at >= since,
                DetectedEvent.resonance_score >= 90
            ).all()
            
            for event in critical_events:
                if not event.source_channel or not event.message_id:
                    continue
                    
                alert_id = f"{event.source_channel}_{event.message_id}"
                if alert_id in self.sent_alerts:
                    continue
                
                # Check if from official source (simplified list)
                officials = ["VA_Kyiv", "KyivCityOfficial", "kpszsu", "ComAFUA", "GeneralStaffZSU"]
                if event.source_channel not in officials and event.resonance_score < 95:
                    continue
                
                text = (
                    f"🔴 *КРИТИЧНА ПОДІЯ*\n\n"
                    f"📍 {event.location_text or 'Київ'}\n"
                    f"📝 {event.message_text[:200]}...\n"
                    f"🏛️ @{event.source_channel}\n"
                    f"⏰ {event.detected_at.strftime('%H:%M') if event.detected_at else 'N/A'}"
                )
                
                try:
                    await self.bot.send_message(self.admin_id, text, parse_mode="Markdown")
                    self.sent_alerts.add(alert_id)
                except Exception as e:
                    print(f"Failed to send critical alert: {e}")
                
                if len(self.sent_alerts) > 100:
                    self.sent_alerts = set(list(self.sent_alerts)[-50:])
                    
        finally:
            db.close()
