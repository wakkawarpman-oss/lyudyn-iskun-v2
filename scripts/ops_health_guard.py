#!/usr/bin/env python3
"""
OKINT-PRO C4ISR Platform: Operational Health Guard & Threshold Monitor.
Periodically audits queue depth, Redis memory usage, database connectivity,
and Parquet data lake integrity. Returns exit code 0 (GREEN) or 1 (ALERT).
"""
import os
import sys
import json
import argparse
import datetime

# Ensure project root in sys.path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import redis
from database.models import SessionLocal, DetectedEvent, HITLFeedbackAudit


def audit_system_health(queue_limit: int = 100, mem_limit_mb: float = 50.0) -> dict:
    health = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "status": "GREEN",
        "alerts": [],
        "metrics": {}
    }

    # 1. Redis Audit
    redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    try:
        r = redis.Redis.from_url(redis_url, socket_timeout=3.0)
        info_mem = r.info("memory")
        used_mem_bytes = info_mem.get("used_memory", 0)
        used_mem_mb = round(used_mem_bytes / (1024 * 1024), 2)
        q_len = r.llen("broadcast_queue")

        health["metrics"]["redis"] = {
            "status": "OK",
            "used_memory_mb": used_mem_mb,
            "broadcast_queue_len": q_len
        }

        if q_len > queue_limit:
            health["status"] = "ALERT"
            health["alerts"].append(f"Queue backlog threshold breached: {q_len} tasks > {queue_limit}")

        if used_mem_mb > mem_limit_mb:
            health["status"] = "ALERT"
            health["alerts"].append(f"Memory threshold breached: {used_mem_mb} MB > {mem_limit_mb} MB")

    except Exception as e:
        health["status"] = "ALERT"
        health["alerts"].append(f"Redis connection failed: {e}")
        health["metrics"]["redis"] = {"status": "ERROR", "error": str(e)}

    # 2. Database Audit
    try:
        db = SessionLocal()
        cutoff_24h = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
        active_events = db.query(DetectedEvent).filter(DetectedEvent.detected_at >= cutoff_24h).count()
        total_hitl = db.query(HITLFeedbackAudit).count()
        db.close()

        health["metrics"]["database"] = {
            "status": "OK",
            "active_events_24h": active_events,
            "total_hitl_audits": total_hitl
        }
    except Exception as dbe:
        health["status"] = "ALERT"
        health["alerts"].append(f"Database query failed: {dbe}")
        health["metrics"]["database"] = {"status": "ERROR", "error": str(dbe)}

    # 3. Parquet Data Lake Audit
    try:
        from worker.data_lake import get_data_lake_stats
        lake = get_data_lake_stats()
        health["metrics"]["data_lake"] = {
            "status": "OK",
            "partitions": lake.get("total_files", 0),
            "records": lake.get("total_records", 0),
            "size_kb": lake.get("total_size_kb", 0)
        }
    except Exception as lke:
        health["metrics"]["data_lake"] = {"status": "WARNING", "error": str(lke)}

    return health


def main():
    parser = argparse.ArgumentParser(description="OKINT-PRO Ops Health Guard")
    parser.add_argument("--queue-limit", type=int, default=100, help="Max queue depth before alert")
    parser.add_argument("--mem-limit-mb", type=float, default=50.0, help="Max Redis memory (MB) before alert")
    args = parser.parse_args()

    result = audit_system_health(queue_limit=args.queue_limit, mem_limit_mb=args.mem_limit_mb)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    if result["status"] == "ALERT":
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
