import pytest
from worker.tasks import _get_tier_info

def test_verifier_tier_mapping():
    assert _get_tier_info("kpszsu") == ("S", 1.0)
    assert _get_tier_info("kyivcityofficial") == ("S", 1.0)
    assert _get_tier_info("monitor_ukr") == ("A", 0.7)
    assert _get_tier_info("kyivoperativ") == ("B", 0.5)

def test_consensus_math():
    # Simulate DB tier logic
    weight_monitor = _get_tier_info("monitor_ukr")[1]
    weight_smi = _get_tier_info("suspilne")[1]
    
    assert weight_monitor + weight_smi >= 1.2
    assert weight_smi + weight_smi < 1.2
