"""Video OSINT: listener/telethon_client.py's size/duration guard, and
bot/handlers/osint.py's handle_video (mirrors handle_photo).

Async handlers are run via asyncio.run() directly rather than
@pytest.mark.asyncio — pytest-asyncio isn't a project dependency (kept out
deliberately during the stabilization sprint, see tests/test_security.py)."""
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import cv2
import numpy as np

from bot.handlers.osint import handle_video
from worker.osint.video_frame_extractor import extract_representative_frame, is_video_file


def _make_test_video(path, frames=20, size=(80, 80)):
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(path, fourcc, 10, size)
    for i in range(frames):
        writer.write(np.full((size[1], size[0], 3), (i * 5 % 256, 40, 90), dtype=np.uint8))
    writer.release()


def test_is_video_file_detects_common_extensions():
    assert is_video_file("clip.mp4")
    assert is_video_file("clip.MOV")
    assert not is_video_file("photo.jpg")
    assert not is_video_file("")


def test_extract_representative_frame_from_real_video(tmp_path):
    video_path = str(tmp_path / "clip.mp4")
    _make_test_video(video_path)
    frame_path = extract_representative_frame(video_path)
    assert frame_path and os.path.exists(frame_path)
    frame = cv2.imread(frame_path)
    assert frame.shape == (80, 80, 3)


def test_extract_representative_frame_missing_file_returns_empty():
    assert extract_representative_frame("/nonexistent/video.mp4") == ""


def test_handle_video_extracts_frame_and_cleans_up_raw_video(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    video_bytes = b""
    real_video_path = str(tmp_path / "source.mp4")
    _make_test_video(real_video_path)
    with open(real_video_path, "rb") as f:
        video_bytes = f.read()

    message = MagicMock()
    message.from_user.id = 999
    message.video.file_id = "vid123"

    bot = MagicMock()
    tg_file = MagicMock()
    tg_file.file_path = "some/remote/path.mp4"
    bot.get_file = AsyncMock(return_value=tg_file)
    downloaded = MagicMock()
    downloaded.read.return_value = video_bytes
    bot.download_file = AsyncMock(return_value=downloaded)

    captured = {}

    async def fake_analysis(msg, user_api_key, effective_key, temp_path):
        captured["temp_path"] = temp_path
        captured["exists_at_call_time"] = os.path.exists(temp_path)

    with patch("bot.handlers.osint._get_effective_openai_key", new=AsyncMock(return_value=(None, "sk-admin-key"))), \
         patch("bot.handlers.osint.is_admin", return_value=True), \
         patch("bot.handlers.osint.safe_send", new=AsyncMock()), \
         patch("bot.handlers.osint._run_photo_osint_analysis", new=fake_analysis):
        asyncio.run(handle_video(message, bot))

    assert captured["exists_at_call_time"] is True
    assert captured["temp_path"].endswith(".jpg")
    # The raw downloaded video file must be removed once the frame is extracted.
    raw_video_temp = f"temp_{message.from_user.id}_vid123.mp4"
    assert not os.path.exists(raw_video_temp)


def test_handle_video_denies_non_admin_without_own_key():
    message = MagicMock()
    message.from_user.id = 111
    bot = MagicMock()

    with patch("bot.handlers.osint._get_effective_openai_key", new=AsyncMock(return_value=(None, None))), \
         patch("bot.handlers.osint.is_admin", return_value=False), \
         patch("bot.handlers.osint.safe_send", new=AsyncMock()) as mock_send:
        asyncio.run(handle_video(message, bot))

    mock_send.assert_called_once()
    assert "потребує ключа OpenAI" in mock_send.call_args[0][1]
    bot.get_file.assert_not_called()
