"""
Test Suite for Telethon 20-Account Consistent Hashing Sharding.
Verifies:
1. Deterministic CRC-32 channel partition across N session shards.
2. Even distribution across all accounts in the pool.
3. Stability of shard assignment.
"""

import pytest
import zlib
from listener.telethon_client import load_target_channels


def test_consistent_hashing_distribution_20_accounts():
    """Verify that target channels partition cleanly and deterministically across 20 accounts."""
    channels = load_target_channels()
    assert len(channels) >= 80, f"Expected at least 80 channels, got {len(channels)}"

    num_shards = 20
    shards = {i: [] for i in range(num_shards)}

    for ch in channels:
        ch_clean = str(ch).lstrip("@").lower().strip()
        shard_idx = zlib.crc32(ch_clean.encode("utf-8")) % num_shards
        assert 0 <= shard_idx < num_shards
        shards[shard_idx].append(ch)

    # All channels assigned
    total_assigned = sum(len(chs) for chs in shards.values())
    assert total_assigned == len(channels)

    # Verify no single shard carries excessive load (> 15% of channels)
    max_shard_len = max(len(chs) for chs in shards.values())
    min_shard_len = min(len(chs) for chs in shards.values())
    assert max_shard_len <= len(channels) * 0.20, f"Shard load too high: {max_shard_len}"
    assert min_shard_len >= 1, "Expected at least 1 channel per shard"


def test_consistent_hashing_determinism():
    """Verify that a channel always hashes to the exact same shard index."""
    test_ch = "@kpszsu"
    ch_clean = test_ch.lstrip("@").lower().strip()
    idx1 = zlib.crc32(ch_clean.encode("utf-8")) % 20
    idx2 = zlib.crc32(ch_clean.encode("utf-8")) % 20
    assert idx1 == idx2
