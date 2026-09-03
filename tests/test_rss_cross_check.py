"""RSS national media outlets (worker/osint/rss_intel.py) were falling
through to the generic USER_GENERATED/Tier C/0.40 default in
worker/source_registry.py — the same weight as an anonymous aggregator
channel. Registered them as MEDIA_OSINT/Tier A/0.70 (matching the existing
Pravda_Gerashchenko entry) so RSS corroboration of a Telegram-sourced
incident actually moves confidence_score/sources_count through the existing
clustering pipeline — no new network call needed."""
from worker.osint.rss_intel import rss_v2
from worker.scoring import calculate_confidence_score
from worker.source_registry import get_source_metadata


def test_all_rss_sources_are_registered_as_media_osint():
    for key in rss_v2.SOURCES:
        meta = get_source_metadata(key)
        assert meta["type"] == "MEDIA_OSINT", f"{key} still falling through to the generic default"
        assert meta["base_weight"] == 0.70


def test_two_rss_sources_corroborating_cross_the_verification_threshold():
    """Before this fix, two unregistered sources at the 0.40 default
    combine to 0.80 -> base_score 40 (Tier 2, "Повідомляється"). Two
    correctly-weighted MEDIA_OSINT sources combine to 1.40 -> crosses the
    1.2 threshold -> base_score 70, which is what flips
    bot/ui_formatter.py's badge towards "Підтверджено"."""
    before_fix_score = calculate_confidence_score(["unregistered_channel_a", "unregistered_channel_b"])
    after_fix_score = calculate_confidence_score(["rss_pravda", "rss_ukrinform"])
    assert before_fix_score == 40
    assert after_fix_score == 70
    assert after_fix_score > before_fix_score


def test_single_rss_source_alone_is_not_enough_for_confirmation():
    """One media report alone should still read as "reported", not
    "confirmed" — matches the existing Tier 2 threshold design, this fix
    only changes what a source IS worth, not the thresholds themselves."""
    score = calculate_confidence_score(["rss_pravda"])
    assert score < 70
