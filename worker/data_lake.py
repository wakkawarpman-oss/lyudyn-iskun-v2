"""
P3.2 Parquet Data Lake — Cold Storage & ML Feature Store.
=========================================================
Exports historical DetectedEvent records to date-partitioned Apache Parquet
columnar storage (year=YYYY/month=MM/events_YYYY-MM-DD.parquet).
Enables longitudinal ML retraining, retrospective incident analytics,
and preserves intelligence before 24h retention purging.
"""
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_DATA_LAKE_DIR = os.getenv("DATA_LAKE_DIR", "data/lake/events")


def export_events_to_dataframe(events: list) -> pd.DataFrame:
    """Converts a list of DetectedEvent SQLAlchemy objects to a normalized pandas DataFrame."""
    rows = []
    for ev in events:
        lat = None
        lon = None
        if hasattr(ev, "geom") and ev.geom is not None:
            try:
                from geoalchemy2.shape import to_shape
                pt = to_shape(ev.geom)
                lat = float(pt.y)
                lon = float(pt.x)
            except Exception:
                pass

        rows.append({
            "id": int(ev.id),
            "incident_id": str(ev.incident_id or ""),
            "detected_at": ev.detected_at,
            "source_channel": str(ev.source_channel or ""),
            "message_id": int(ev.message_id or 0),
            "message_text": str(ev.message_text or ""),
            "event_type": str(ev.event_type or ""),
            "location_text": str(ev.location_text or ""),
            "latitude": lat,
            "longitude": lon,
            "significance_score": int(ev.significance_score or 50),
            "confidence_score": int(ev.confidence_score or 50),
            "resonance_score": int(ev.resonance_score or 50),
            "verification_status": str(ev.verification_status or "UNVERIFIED_SINGLE_SOURCE"),
            "sources_count": int(ev.sources_count or 1),
            "sources_list": str(ev.sources_list or ""),
            "is_official": bool(ev.is_official),
            "geo_precision": str(ev.geo_precision or "settlement"),
            "geo_radius_m": int(ev.geo_radius_m or 2000),
            "image_phash": str(ev.image_phash or ""),
            "has_media": bool(ev.has_media),
            "is_fallback_geo": bool(ev.is_fallback_geo),
        })

    return pd.DataFrame(rows)


def archive_events_to_parquet(
    db,
    threshold_date: Optional[datetime] = None,
    output_dir: str = DEFAULT_DATA_LAKE_DIR,
) -> Dict[str, Any]:
    """Archives DetectedEvents before threshold_date into partitioned Parquet files."""
    from database.models import DetectedEvent

    query = db.query(DetectedEvent)
    if threshold_date:
        query = query.filter(DetectedEvent.detected_at <= threshold_date)

    events = query.order_by(DetectedEvent.detected_at.asc()).all()
    if not events:
        return {"status": "skipped", "reason": "no_events_found", "archived_records": 0}

    df = export_events_to_dataframe(events)
    if df.empty:
        return {"status": "skipped", "reason": "empty_dataframe", "archived_records": 0}

    # Group by event date for partitioned storage
    df["date_str"] = df["detected_at"].dt.strftime("%Y-%m-%d")
    df["year"] = df["detected_at"].dt.strftime("%Y")
    df["month"] = df["detected_at"].dt.strftime("%m")

    written_files = []
    total_records = 0

    for date_val, group in df.groupby("date_str"):
        year_str = group["year"].iloc[0]
        month_str = group["month"].iloc[0]
        part_dir = os.path.join(output_dir, f"year={year_str}", f"month={month_str}")
        os.makedirs(part_dir, exist_ok=True)
        file_path = os.path.join(part_dir, f"events_{date_val}.parquet")

        clean_group = group.drop(columns=["date_str", "year", "month"])

        if os.path.exists(file_path):
            try:
                existing_df = pd.read_parquet(file_path)
                combined = pd.concat([existing_df, clean_group], ignore_index=True)
                combined = combined.drop_duplicates(subset=["id"], keep="last")
                combined.to_parquet(file_path, index=False, compression="snappy")
                total_records += len(clean_group)
            except Exception as e:
                logger.warning(f"Merge error for {file_path}: {e}, overwriting")
                clean_group.to_parquet(file_path, index=False, compression="snappy")
                total_records += len(clean_group)
        else:
            clean_group.to_parquet(file_path, index=False, compression="snappy")
            total_records += len(clean_group)

        written_files.append(file_path)

    logger.info(f"Parquet Data Lake: Archived {total_records} events into {len(written_files)} files.")
    return {
        "status": "success",
        "archived_records": total_records,
        "files_written": len(written_files),
        "target_partitions": written_files,
    }


def get_data_lake_stats(base_dir: str = DEFAULT_DATA_LAKE_DIR) -> Dict[str, Any]:
    """Inspects the Parquet data lake and computes storage metrics."""
    if not os.path.exists(base_dir):
        return {
            "status": "empty",
            "base_dir": base_dir,
            "total_files": 0,
            "total_size_kb": 0.0,
            "partitions": [],
            "total_records": 0,
        }

    total_files = 0
    total_bytes = 0
    partitions = []
    total_records = 0

    for root, dirs, files in os.walk(base_dir):
        for f in files:
            if f.endswith(".parquet"):
                full_path = os.path.join(root, f)
                total_files += 1
                sz = os.path.getsize(full_path)
                total_bytes += sz
                try:
                    df = pd.read_parquet(full_path)
                    rec_count = len(df)
                    total_records += rec_count
                except Exception:
                    rec_count = 0
                rel_path = os.path.relpath(full_path, base_dir)
                partitions.append({"file": rel_path, "size_kb": round(sz / 1024.0, 2), "records": rec_count})

    return {
        "status": "active" if total_files > 0 else "empty",
        "base_dir": base_dir,
        "total_files": total_files,
        "total_size_kb": round(total_bytes / 1024.0, 2),
        "total_records": total_records,
        "partitions": partitions,
    }
