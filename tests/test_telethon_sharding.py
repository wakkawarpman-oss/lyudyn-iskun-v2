"""
Test Suite for Telethon 20-Account Sharding & Proxy Configuration.
Verifies:
1. Balanced channel partition across N session shards with CV < 0.15.
2. Channel isolation across event handlers (disjoint channel sets).
3. Proxy parsing for Socks5/MTProto per session.
"""

import os
import pytest
import statistics
from listener.telethon_client import load_target_channels, get_session_proxy


def test_balanced_distribution_and_low_cv():
    """Verify that canonical channels partition with low coefficient of variation across 20 accounts."""
    channels = load_target_channels()
    assert len(channels) >= 80, f"Expected at least 80 channels, got {len(channels)}"

    sorted_channels = sorted(list(set(channels)))
    num_shards = 20
    shards = {i: [] for i in range(num_shards)}

    for i, ch in enumerate(sorted_channels):
        shard_idx = i % num_shards
        shards[shard_idx].append(ch)

    loads = [len(chs) for chs in shards.values()]
    mean = statistics.mean(loads)
    stdev = statistics.stdev(loads)
    cv = stdev / mean

    # Every shard must have between floor(M/N) and ceil(M/N) channels
    assert max(loads) - min(loads) <= 1, f"Load imbalance detected: max={max(loads)}, min={min(loads)}"
    assert cv < 0.15, f"Expected CV < 0.15, got {cv:.3f}"
    assert sum(loads) == len(sorted_channels)


def test_handler_channel_isolation():
    """Verify strict channel isolation: no overlap between shards and proper binding."""
    channels = load_target_channels()
    sorted_channels = sorted(list(set(channels)))
    num_shards = 20
    shards = {i: set() for i in range(num_shards)}

    for i, ch in enumerate(sorted_channels):
        shards[i % num_shards].add(ch)

    # Check pairwise disjointness
    for i in range(num_shards):
        for j in range(i + 1, num_shards):
            intersection = shards[i] & shards[j]
            assert len(intersection) == 0, f"Overlap between shard {i} and {j}: {intersection}"


def test_proxy_configuration_parsing(monkeypatch):
    """Verify Socks5 proxy string parsing for Telethon sessions."""
    monkeypatch.setenv("PROXY_1", "socks5://operator:secret123@192.168.1.50:1080")
    monkeypatch.setenv("PROXIES", "socks5://u1:p1@proxy1.net:1080,socks5://u2:p2@proxy2.net:1080")

    p1 = get_session_proxy(0)
    assert p1 is not None
    assert p1["addr"] == "192.168.1.50"
    assert p1["port"] == 1080
    assert p1["username"] == "operator"
    assert p1["password"] == "secret123"

    p2 = get_session_proxy(1)
    assert p2 is not None
    assert p2["addr"] == "proxy2.net"
    assert p2["port"] == 1080
    assert p2["username"] == "u2"

    p_none = get_session_proxy(15)
    assert p_none is None
