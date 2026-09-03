import os
import json
import asyncio
from datetime import datetime
import tempfile
from aiogram import Bot
from database.models import SessionLocal, DetectedEvent

class DatabaseBackup:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.admin_id = os.getenv("ADMIN_ID", "123456789")

    async def run(self):
        # Run backup every 24 hours
        while True:
            await asyncio.sleep(86400)
            await self.backup_to_telegram()

    async def backup_to_telegram(self):
        if not self.bot or not self.admin_id:
            return
            
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M")
        
        try:
            db = SessionLocal()
            events = db.query(DetectedEvent).all()
            
            data = []
            for e in events:
                data.append({
                    "id": e.id,
                    "channel": e.source_channel,
                    "message_id": e.message_id,
                    "text": e.message_text,
                    "event_type": e.event_type,
                    "latitude": e.latitude,
                    "longitude": e.longitude,
                    "resonance_score": e.resonance_score,
                    "timestamp": e.detected_at.isoformat() if e.detected_at else None
                })
            db.close()
            
            with tempfile.NamedTemporaryFile(mode='w+', suffix='.json', delete=False) as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f_name = f.name
            
            from aiogram.types import FSInputFile
            file = FSInputFile(f_name, filename=f"iskun_backup_{timestamp}.json")
            
            file_size_mb = os.path.getsize(f_name) / 1024 / 1024
            
            await self.bot.send_document(
                self.admin_id,
                document=file,
                caption=f"📦 Автобекап БД\n{timestamp}\nРозмір: {file_size_mb:.1f} MB\nЗаписів: {len(data)}"
            )
            
            os.remove(f_name)
        except Exception as e:
            print(f"Backup error: {e}")
