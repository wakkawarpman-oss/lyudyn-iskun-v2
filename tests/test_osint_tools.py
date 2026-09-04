from worker.osint.similar_channels import (
    classify_channel_affiliation,
    discover_similar_channels_sync
)
from worker.osint.apt_matcher import analyze_threat_actors


def test_classify_channel_affiliation():
    assert classify_channel_affiliation("kpszsu") == "UKRAINIAN_OFFICIAL"
    assert classify_channel_affiliation("va_kyiv") == "UKRAINIAN_OFFICIAL"
    assert classify_channel_affiliation("rybar") == "ADVERSARY_PROPAGANDA"
    assert classify_channel_affiliation("readovkanews") == "ADVERSARY_PROPAGANDA"
    assert classify_channel_affiliation("unknown_civilian_chat") == "CIVILIAN_OR_OSINT"


def test_discover_similar_channels_sync():
    res = discover_similar_channels_sync("kpszsu")
    assert isinstance(res, list)
    assert len(res) >= 1
    usernames = [c["username"] for c in res]
    assert "va_kyiv" in usernames or "kpszsu" in usernames


def test_apt_threat_matcher_gamaredon():
    text = "Фіксується розсилка шкідливого ПЗ Pteranodon від групи Gamaredon (Armageddon) через t.me/c2_test C2."
    result = analyze_threat_actors(text)
    assert result["matched"] is True
    assert any(g["group"] == "Gamaredon" for g in result["matched_groups"])
    assert result["threat_level"] in ["HIGH", "CRITICAL"]
    assert result["cyber_kinetic_correlation"] is True


def test_apt_threat_matcher_clean():
    text = "Відбій повітряної тривоги в Києві. Відновлюється рух метро."
    result = analyze_threat_actors(text)
    assert result["matched"] is False
    assert result["threat_level"] == "NONE"


def test_openwebui_tools_manifest():
    from api.routes.openwebui_tools import get_tools_manifest
    manifest = get_tools_manifest()
    assert "tools" in manifest
    tool_names = [t["name"] for t in manifest["tools"]]
    assert "c4isr_radar_threats" in tool_names
    assert "c4isr_alert_status" in tool_names
    assert "c4isr_similar_channels" in tool_names
    assert "c4isr_infrastructure_proximity" in tool_names
    assert "c4isr_apt_threat_scan" in tool_names
