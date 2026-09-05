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
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    result_expires=3600,
    result_extended=False,
    task_ignore_result=True,
    task_default_queue='messages',
    task_routes={
        'worker.tasks.process_message': {'queue': 'messages'},
        'worker.tasks.pipeline_extract': {'queue': 'messages'},
        'worker.tasks.pipeline_geocode': {'queue': 'messages'},
        'worker.tasks.pipeline_cluster_and_save': {'queue': 'messages'},
        'worker.tasks.task_process_llm': {'queue': 'llm_tasks'},
    }
)

# Celery Beat schedule for database cleanup
app.conf.beat_schedule = {
    'cleanup-old-events-every-night': {
        'task': 'worker.tasks.cleanup_old_events',
        'schedule': crontab(hour=3, minute=0), # Run every night at 03:00 UTC
    },
    'watchdog-health-check': {
        'task': 'worker.tasks.run_watchdog',
        'schedule': 900.0, # Every 15 minutes (15 * 60 seconds)
    },
    'fetch-rss-news': {
        'task': 'worker.tasks.fetch_rss_news_task',
        'schedule': 300.0, # Every 5 minutes
    },
    'auto-sanitize-tactical-events': {
        'task': 'worker.tasks.auto_sanitize_tactical_events_task',
        'schedule': 30.0, # Every 30 seconds
    },
}
