"""Anti-IPSO perceptual-hash duplicate detection.

Catches a recycled or archival photo reposted as a "new" incident — the
kind of thing IPSO/disinfo actors do to fake fresh damage. Not a
cryptographic hash: perceptual hashing tolerates recompression, resizing,
and minor edits (crops, watermarks) that would defeat an exact-match check.
"""
import datetime
import logging

import imagehash
from PIL import Image

logger = logging.getLogger(__name__)

# Hamming distance below which two images are treated as "the same photo".
# imagehash.phash produces 64-bit hashes; 0 = identical, ~10+ = visually
# different images. 5 tolerates light recompression/cropping/watermarking.
SIMILARITY_THRESHOLD = 5


def compute_phash(image_path: str) -> str:
    """Returns a hex-encoded perceptual hash, or "" if the file can't be read."""
    try:
        with Image.open(image_path) as img:
            return str(imagehash.phash(img))
    except Exception as e:
        logger.warning(f"pHash computation failed for {image_path}: {e}")
        return ""


def find_similar_event(db, phash_hex: str, lookback_days: int = 30):
    """Returns the most recent DetectedEvent whose image_phash is within
    SIMILARITY_THRESHOLD of phash_hex, or None. Imports DetectedEvent lazily
    to avoid a circular import (database.models doesn't import this module,
    but keeping the import local here matches how other worker/osint/*
    modules that need the model do it)."""
    from database.models import DetectedEvent

    if not phash_hex:
        return None

    try:
        target = imagehash.hex_to_hash(phash_hex)
    except Exception as e:
        logger.warning(f"Invalid phash '{phash_hex}': {e}")
        return None

    threshold_date = datetime.datetime.utcnow() - datetime.timedelta(days=lookback_days)
    candidates = (
        db.query(DetectedEvent)
        .filter(
            DetectedEvent.image_phash.isnot(None),
            DetectedEvent.detected_at >= threshold_date,
        )
        .order_by(DetectedEvent.detected_at.desc())
        .limit(500)
        .all()
    )

    for candidate in candidates:
        try:
            candidate_hash = imagehash.hex_to_hash(candidate.image_phash)
        except Exception:
            continue
        if target - candidate_hash <= SIMILARITY_THRESHOLD:
            return candidate

    return None
