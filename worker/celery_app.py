import os
from celery import Celery
from celery.schedules import crontab

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

app = Celery(
    'lyudyn_iskun',
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=['worker.tasks']
)

app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_routes={
        'worker.tasks.process_message': {'queue': 'messages'}
    }
)

# Celery Beat schedule for database cleanup
app.conf.beat_schedule = {
    'cleanup-old-events-every-night': {
        'task': 'worker.tasks.cleanup_old_events',
        'schedule': crontab(hour=3, minute=0), # Run every night at 03:00 UTC
    },
}
