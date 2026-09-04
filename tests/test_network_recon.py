from worker.osint.network_recon import (
    get_tot_telecom_status,
    parse_crt_sh_certificates,
    TOT_TELECOM_REGISTRY
)


def test_tot_telecom_registry_integrity():
    assert len(TOT_TELECOM_REGISTRY) >= 5
    asns = [item["asn"] for item in TOT_TELECOM_REGISTRY]
    assert "AS201776" in asns  # Miranda Media
    assert "AS48287" in asns   # Krymtelecom
    assert "AS208571" in asns  # Tavriya Telecom

    for item in TOT_TELECOM_REGISTRY:
        assert "name" in item
        assert "region" in item
        assert "upstream_transits" in item
        assert "status" in item
        assert "risk_level" in item


def test_get_tot_telecom_status():
    status = get_tot_telecom_status()
    assert status["status"] == "monitored"
    assert status["total_monitored_asns"] >= 5
    assert status["critical_hijacked_asns"] >= 2
    assert "bgp_methodology" in status
    assert "AS12389" in status["bgp_methodology"]["primary_upstream"]


def test_parse_crt_sh_certificates():
    raw_mock = [
        {"name_value": "c2.threat-actor.org\napi.threat-actor.org", "issuer_name": "Let's Encrypt", "entry_timestamp": "2026-08-01"},
        {"name_value": "login.threat-actor.org", "issuer_name": "ZeroSSL", "entry_timestamp": "2026-08-15"},
        {"name_value": "unrelated.domain.com", "issuer_name": "DigiCert", "entry_timestamp": "2026-08-20"},
        {"name_value": "c2.threat-actor.org", "issuer_name": "Let's Encrypt", "entry_timestamp": "2026-08-22"} # Duplicate
    ]
    parsed = parse_crt_sh_certificates("threat-actor.org", raw_mock)
    subdomains = [p["subdomain"] for p in parsed]
    assert "c2.threat-actor.org" in subdomains
    assert "api.threat-actor.org" in subdomains
    assert "login.threat-actor.org" in subdomains
    assert "unrelated.domain.com" not in subdomains
    assert len(subdomains) == 3  # Deduplicated
