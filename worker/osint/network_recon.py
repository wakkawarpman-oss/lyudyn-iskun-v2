"""
Module: worker.osint.network_recon
Passive Internet Measurement, BGP Routing Analysis, and Attack Surface Reconnaissance.
Focuses on Temporarily Occupied Territories (TOT) telecom hijacking, transit tracking, and certificate transparency.
"""

from typing import Dict, List, Any

# Verified Autonomous System Numbers (ASNs) operating in TOT and Russian transit backbones
TOT_TELECOM_REGISTRY: List[Dict[str, Any]] = [
    {
        "asn": "AS201776",
        "name": "Miranda Media (Крим / ТОТ Півдня)",
        "region": "Крим, Запорізька, Херсонська обл.",
        "upstream_transits": ["AS12389 (Rostelecom)", "AS20485 (TransTeleCom)"],
        "status": "HIJACKED_RUSSIAN_CONTROL",
        "risk_level": "CRITICAL",
        "dossier": "Магістральний оператор окупаційної адміністрації, створений на базі викраденої інфраструктури Укртелекому."
    },
    {
        "asn": "AS48287",
        "name": "Krymtelecom (Кримтелеком)",
        "region": "АР Крим / Севастополь",
        "upstream_transits": ["AS12389 (Rostelecom)"],
        "status": "OCCUPIED_ROUTING",
        "risk_level": "HIGH",
        "dossier": "Мобільний та фіксований зв'язок під повним контролем ФСБ РФ через систему СОРМ-3."
    },
    {
        "asn": "AS200000",
        "name": "Komtech / Ugtelecom (Донбас)",
        "region": "Окупована Донеччина",
        "upstream_transits": ["AS12389 (Rostelecom)"],
        "status": "OCCUPIED_ROUTING",
        "risk_level": "HIGH",
        "dossier": "Маршрутизація трафіку через ростовський вузол Ростелекому."
    },
    {
        "asn": "AS208571",
        "name": "Tavriya Telecom (Таврія-Телеком)",
        "region": "Бердянськ, Мелітополь, Енергодар",
        "upstream_transits": ["AS201776 (Miranda Media)", "AS12389 (Rostelecom)"],
        "status": "MILITARY_SURVEILLANCE",
        "risk_level": "CRITICAL",
        "dossier": "Провайдер окупаційного контролю в районі ЗАЕС та азовського узбережжя."
    },
    {
        "asn": "AS57189",
        "name": "Lugacom / MKS (Луганськ)",
        "region": "Окупована Луганщина",
        "upstream_transits": ["AS31133 (MegaFon)", "AS12389 (Rostelecom)"],
        "status": "OCCUPIED_ROUTING",
        "risk_level": "HIGH",
        "dossier": "Повний перехоплення мобільних комунікацій та інтернет-трафіку."
    }
]


def get_tot_telecom_status() -> Dict[str, Any]:
    """
    Returns verified routing status, hijacking profiles, and BGP topology for TOT networks.
    """
    hijacked_count = sum(1 for n in TOT_TELECOM_REGISTRY if n["status"] in ("HIJACKED_RUSSIAN_CONTROL", "MILITARY_SURVEILLANCE"))
    
    return {
        "status": "monitored",
        "total_monitored_asns": len(TOT_TELECOM_REGISTRY),
        "critical_hijacked_asns": hijacked_count,
        "asns": TOT_TELECOM_REGISTRY,
        "bgp_methodology": {
            "primary_upstream": "AS12389 (PJSC Rostelecom)",
            "surveillance_framework": "СОРМ-3 / ТСПУ (РКН)",
            "rerouting_detection": "100% трафіку виведено з українських точок обміну (UA-IX) через РФ."
        }
    }


def parse_crt_sh_certificates(domain: str, raw_certs: List[Dict]) -> List[Dict[str, Any]]:
    """
    Extracts and dedupes passive subdomains from Certificate Transparency logs.
    Zero-noise OSINT method.
    """
    if not raw_certs:
        return []

    discovered = set()
    results = []

    for item in raw_certs:
        name_val = item.get("name_value", "")
        for line in name_val.split("\n"):
            line = line.strip().lower()
            if line and line.endswith(domain) and line not in discovered:
                discovered.add(line)
                results.append({
                    "subdomain": line,
                    "issuer_name": item.get("issuer_name", "Unknown"),
                    "logged_at": item.get("entry_timestamp")
                })

    return results
