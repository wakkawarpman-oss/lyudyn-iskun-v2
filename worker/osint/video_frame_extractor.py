"""Extracts one representative frame from a video so it can go through the
existing photo OSINT pipeline (GeoSpy AI, Vision AI, perceptual-hash dedup)
unchanged. EXIF won't find GPS data in a frame decoded from video — that's
expected, not a bug; video files rarely carry usable embedded GPS anyway.
"""
import logging
import os

import cv2

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = (".mp4", ".mov", ".mkv", ".avi", ".webm")


def is_video_file(path: str) -> bool:
    return bool(path) and path.lower().endswith(VIDEO_EXTENSIONS)


def extract_representative_frame(video_path: str) -> str:
    """Saves a frame from roughly the middle of the video as a .jpg next to
    it and returns its path, or "" on failure. The middle frame is used
    instead of the first because opening/closing shots are often black,
    motion-blurred, or a title card."""
    if not video_path or not os.path.exists(video_path):
        return ""

    cap = cv2.VideoCapture(video_path)
    try:
        if not cap.isOpened():
            logger.warning(f"Could not open video for frame extraction: {video_path}")
            return ""

        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        middle_frame_idx = frame_count // 2 if frame_count > 0 else 0
        cap.set(cv2.CAP_PROP_POS_FRAMES, middle_frame_idx)

        ok, frame = cap.read()
        if not ok:
            # Middle frame failed to decode (some containers report a frame
            # count that doesn't seek reliably) — fall back to the first frame.
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = cap.read()
        if not ok:
            logger.warning(f"Could not decode any frame from: {video_path}")
            return ""

        frame_path = f"{os.path.splitext(video_path)[0]}_frame.jpg"
        cv2.imwrite(frame_path, frame)
        return frame_path
    finally:
        cap.release()
