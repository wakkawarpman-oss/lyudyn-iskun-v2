import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from PIL import Image

from worker.osint.image_dedup import compute_phash, find_similar_event


def _make_test_image(path, seed=0, size=(200, 200)):
    img = Image.new("RGB", size)
    for x in range(size[0]):
        for y in range(size[1]):
            img.putpixel((x, y), ((x + seed) % 256, (y + seed) % 256, (x + y + seed) % 256))
    img.save(path)


def test_compute_phash_returns_hex_string(tmp_path):
    p = str(tmp_path / "a.jpg")
    _make_test_image(p)
    h = compute_phash(p)
    assert isinstance(h, str)
    assert len(h) == 16  # 64-bit phash, hex-encoded


def test_compute_phash_missing_file_returns_empty_string():
    assert compute_phash("/nonexistent/path.jpg") == ""


def test_near_duplicate_photo_is_detected_as_similar(tmp_path):
    original = str(tmp_path / "orig.jpg")
    recompressed = str(tmp_path / "recompressed.jpg")
    different = str(tmp_path / "different.jpg")

    _make_test_image(original, seed=0)
    Image.open(original).crop((2, 2, 198, 198)).resize((200, 200)).save(recompressed, quality=80)
    _make_test_image(different, seed=123)

    original_hash = compute_phash(original)
    recompressed_hash = compute_phash(recompressed)
    different_hash = compute_phash(different)

    existing_event = SimpleNamespace(
        id=1,
        incident_id="INC-TEST-1",
        image_phash=original_hash,
        detected_at=datetime.datetime.utcnow(),
        location_text="Оболонь",
    )

    fake_query = MagicMock()
    fake_query.filter.return_value = fake_query
    fake_query.order_by.return_value = fake_query
    fake_query.limit.return_value = fake_query
    fake_query.all.return_value = [existing_event]
    fake_db = MagicMock()
    fake_db.query.return_value = fake_query

    # A recompressed/cropped copy of the same photo IS flagged as similar.
    match = find_similar_event(fake_db, recompressed_hash)
    assert match is existing_event

    # A genuinely different photo is NOT flagged.
    fake_query.all.return_value = [existing_event]
    no_match = find_similar_event(fake_db, different_hash)
    assert no_match is None


def test_find_similar_event_handles_empty_hash():
    fake_db = MagicMock()
    assert find_similar_event(fake_db, "") is None
    fake_db.query.assert_not_called()
