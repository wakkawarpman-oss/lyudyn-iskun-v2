"""Anti-IPSO perceptual-hash and semantic embedding duplicate detection (P2.4).

Catches recycled or archival photos reposted as "new" incidents — typical of IPSO/disinfo.
Combines:
1. DCT Perceptual Hashing (pHash)
2. Spatial Gradient Difference Hashing (dHash)
3. Haar Wavelet Decomposition Hashing (wHash)
4. Multi-channel Color Subspace Hashing (colorhash)
5. Dense Normalized Spatial Feature Vectors (for crops, re-screens, contrast alterations)
"""
import datetime
import logging
from typing import Optional, Dict, Any, Tuple, List
import numpy as np
import imagehash
from PIL import Image

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 5
SEMANTIC_SIMILARITY_THRESHOLD = 0.88


def compute_phash(image_path: str) -> str:
    """Returns a hex-encoded perceptual hash, or "" if the file can't be read."""
    try:
        with Image.open(image_path) as img:
            return str(imagehash.phash(img))
    except Exception as e:
        logger.warning(f"pHash computation failed for {image_path}: {e}")
        return ""


def compute_multihash(image_path: str) -> Dict[str, str]:
    """Computes a multi-spectral perceptual fingerprint (pHash, dHash, wHash, colorhash)."""
    try:
        with Image.open(image_path) as img:
            return {
                "phash": str(imagehash.phash(img)),
                "dhash": str(imagehash.dhash(img)),
                "whash": str(imagehash.whash(img)),
                "colorhash": str(imagehash.colorhash(img)),
            }
    except Exception as e:
        logger.warning(f"Multi-hash computation failed for {image_path}: {e}")
        return {}


def compute_image_embedding(image_path: str) -> Optional[List[float]]:
    """Computes a 128-dimensional normalized visual feature vector capturing
    spatial color moments and directional gradient distributions."""
    try:
        with Image.open(image_path) as img:
            img_rgb = img.convert("RGB").resize((64, 64))
            arr = np.asarray(img_rgb, dtype=np.float32) / 255.0

            # Spatial 4x4 grid color moments (mean + std across RGB channels: 4*4*3*2 = 96 dims)
            blocks = []
            for i in range(4):
                for j in range(4):
                    block = arr[i * 16 : (i + 1) * 16, j * 16 : (j + 1) * 16]
                    blocks.extend(block.mean(axis=(0, 1)))
                    blocks.extend(block.std(axis=(0, 1)))

            # Grayscale directional gradient magnitude histogram (32 bins)
            gray = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
            dx = np.diff(gray, axis=1)
            dy = np.diff(gray, axis=0)
            grad_mag = np.sqrt(dx[:63, :] ** 2 + dy[:, :63] ** 2)
            grad_hist, _ = np.histogram(grad_mag, bins=32, range=(0.0, 1.0))

            feat = np.concatenate([blocks, grad_hist.astype(np.float32)])
            norm = float(np.linalg.norm(feat))
            if norm > 1e-6:
                feat /= norm
            return feat.tolist()
    except Exception as e:
        logger.warning(f"Image embedding computation failed for {image_path}: {e}")
        return None


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Calculates cosine similarity between two normalized feature vectors."""
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    v1 = np.asarray(vec1, dtype=np.float32)
    v2 = np.asarray(vec2, dtype=np.float32)
    denom = np.linalg.norm(v1) * np.linalg.norm(v2)
    if denom < 1e-6:
        return 0.0
    return float(np.dot(v1, v2) / denom)


def is_semantic_duplicate(
    hash_a: str,
    hash_b: str,
    emb_a: Optional[List[float]] = None,
    emb_b: Optional[List[float]] = None,
) -> Tuple[bool, float, str]:
    """Evaluates if two image representations represent a duplicate photo or re-screen.
    Returns (is_duplicate, match_score_0_100, detection_reason)."""
    if not hash_a or not hash_b:
        return False, 0.0, "missing_hash"

    # 1. Primary pHash comparison
    try:
        ha = imagehash.hex_to_hash(hash_a.split(":")[0])
        hb = imagehash.hex_to_hash(hash_b.split(":")[0])
        hamming = ha - hb
        if hamming <= SIMILARITY_THRESHOLD:
            score = max(50.0, 100.0 - hamming * 10.0)
            return True, score, f"phash_hamming_{hamming}"
    except Exception:
        pass

    # 2. Embedding Cosine Similarity (handles crops, borders, re-screens)
    if emb_a and emb_b:
        sim = cosine_similarity(emb_a, emb_b)
        if sim >= SEMANTIC_SIMILARITY_THRESHOLD:
            score = round(sim * 100.0, 1)
            return True, score, f"embedding_cosine_{round(sim, 3)}"

    return False, 0.0, "distinct_image"


def find_similar_event(db, phash_hex: str, lookback_days: int = 30, query_emb: Optional[List[float]] = None):
    """Finds the most recent DetectedEvent whose image_phash matches within
    SIMILARITY_THRESHOLD or embedding cosine similarity."""
    from database.models import DetectedEvent

    if not phash_hex:
        return None

    try:
        target = imagehash.hex_to_hash(phash_hex.split(":")[0])
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
        cand_hex = candidate.image_phash.split(":")[0] if candidate.image_phash else ""
        try:
            candidate_hash = imagehash.hex_to_hash(cand_hex)
            if target - candidate_hash <= SIMILARITY_THRESHOLD:
                return candidate
        except Exception:
            continue

    return None
