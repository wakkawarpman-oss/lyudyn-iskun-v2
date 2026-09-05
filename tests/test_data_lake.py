import os
import shutil
import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from worker.data_lake import (
    export_events_to_dataframe,
    archive_events_to_parquet,
    get_data_lake_stats,
)


def test_export_events_to_dataframe():
    now = datetime.datetime.utcnow()
    events = [
        SimpleNamespace(
            id=1,
            incident_id="INC-20260904-OBOLON",
            detected_at=now,
            source_channel="@kiev_real",
            message_id=123,
            message_text="Вибух в районі Оболоні",
            event_type="explosion",
            location_text="Оболонь",
            significance_score=85,
            confidence_score=90,
            resonance_score=88,
            verification_status="VERIFIED",
            sources_count=3,
            sources_list="@kiev_real,@alarm",
            is_official=False,
            geo_precision="district",
            geo_radius_m=1500,
            image_phash="abc123def4567890",
            has_media=True,
            is_fallback_geo=False,
            geom=None,
        )
    ]

    df = export_events_to_dataframe(events)
    assert len(df) == 1
    assert df["incident_id"].iloc[0] == "INC-20260904-OBOLON"
    assert df["significance_score"].iloc[0] == 85
    assert df["confidence_score"].iloc[0] == 90
    assert df["event_type"].iloc[0] == "explosion"


def test_archive_events_to_parquet_and_stats(tmp_path):
    lake_dir = str(tmp_path / "lake")
    now = datetime.datetime(2026, 9, 4, 12, 0, 0)
    events = [
        SimpleNamespace(
            id=i,
            incident_id=f"INC-{i}",
            detected_at=now + datetime.timedelta(hours=i),
            source_channel="@channel",
            message_id=100 + i,
            message_text=f"Подія {i}",
            event_type="air_defense",
            location_text="Київ",
            significance_score=70,
            confidence_score=80,
            resonance_score=75,
            verification_status="VERIFIED",
            sources_count=1,
            sources_list="@channel",
            is_official=True,
            geo_precision="settlement",
            geo_radius_m=2000,
            image_phash="1234567812345678",
            has_media=False,
            is_fallback_geo=False,
            geom=None,
        )
        for i in range(5)
    ]

    mock_query = MagicMock()
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.all.return_value = events

    mock_db = MagicMock()
    mock_db.query.return_value = mock_query

    # 1. First archive run
    res = archive_events_to_parquet(mock_db, output_dir=lake_dir)
    assert res["status"] == "success"
    assert res["archived_records"] == 5
    assert res["files_written"] == 1

    # Check partitioned directory structure
    expected_part = os.path.join(lake_dir, "year=2026", "month=09")
    assert os.path.exists(expected_part)
    parquet_file = os.path.join(expected_part, "events_2026-09-04.parquet")
    assert os.path.exists(parquet_file)

    # 2. Read back parquet with pandas
    saved_df = pd.read_parquet(parquet_file)
    assert len(saved_df) == 5
    assert list(saved_df["id"]) == [0, 1, 2, 3, 4]

    # 3. Check data lake stats
    stats = get_data_lake_stats(lake_dir)
    assert stats["status"] == "active"
    assert stats["total_files"] == 1
    assert stats["total_records"] == 5
    assert stats["total_size_kb"] > 0
