"""
Module: worker.osint.apt_matcher
Correlates incoming OSINT intelligence with MITRE ATT&CK Enterprise Matrix TTPs and APT group signatures.
Focuses on threat actors active in Ukraine (Gamaredon, Sandworm, APT28/Fancy Bear, Volt Typhoon, TA2541).
"""

import re
from typing import Dict, Any

# Threat actor profiles mapped from ATT&CK & Threat Intelligence Wiki
APT_SIGNATURE_DB = {
    "Gamaredon": {
        "aliases": ["Armageddon", "Primitive Bear", "Shuckworm", "FSB Center 18"],
        "target_sectors": ["military", "government", "critical_infrastructure", "civilian_bots"],
        "malware": ["pteranodon", "quietsieve", "powerpunch", "ultrareach"],
        "tactics": [
            "T1102.001 (Dead Drop Resolver via Telegram / GitHub)",
            "T1566.001 (Spearphishing Attachment with VBA / COM Interop)",
            "T1053.005 (Scheduled Task for Persistence)"
        ],
        "regex": r"(pteranodon|quietsieve|powerpunch|gamaredon|shuckworm|armageddon)"
    },
    "Sandworm": {
        "aliases": ["Unit 74455", "Voodoo Bear", "TeleBots", "BlackEnergy"],
        "target_sectors": ["energy_grid", "telecom", "railways", "scada"],
        "malware": ["industroyer", "industroyer2", "caddywiper", "hermeticwiper", "blackenergy"],
        "tactics": [
            "T1485 (Data Destruction / Disk Wipe)",
            "T0855 (Unauthorized Command Message / SCADA Substation Manipulation)"
        ],
        "regex": r"(industroyer|caddywiper|hermeticwiper|blackenergy|sandworm)"
    },
    "Volt Typhoon": {
        "aliases": ["Bronze Silhouette", "Vanguard Panda"],
        "target_sectors": ["communications", "transportation", "water", "maritime"],
        "malware": ["fast reverse proxy", "earthworm", "impacket", "wmi"],
        "tactics": [
            "T1036.005 (Masquerading legitimate files like Win.exe, watchdogd.exe)",
            "T1049 (System Network Connections Discovery via netsh/netstat)"
        ],
        "regex": r"(volt typhoon|earthworm|frp proxy|fast reverse proxy)"
    },
    "TA2541": {
        "aliases": ["Aviation Criminal Actor"],
        "target_sectors": ["aviation", "aerospace", "defense_manufacturing"],
        "malware": ["agent tesla", "asyncrat", "netwire", "warzonerat", "revenge rat"],
        "tactics": [
            "T1566.002 (Spearphishing Link to Google Drive/Discord)",
            "T1055 (Process Hollowing)"
        ],
        "regex": r"(asyncrat|agent tesla|netwire|warzonerat|revenge rat|imminent monitor)"
    },
    "Alabuga-Albatross": {
        "aliases": ["ТОВ Альбатрос", "ОЕЗ Алабуга", "Проєкт Dolphin 632", "AlabugaLeaks", "Albatros"],
        "target_sectors": ["energy_grid", "substations_110_750kv", "civilian_infrastructure"],
        "malware": ["shahed-136", "герань-2", "герань-3", "комета-м", "kometa-m", "md-550"],
        "tactics": [
            "T1071 (CRPA Antenna Kometa-M Anti-Jamming Guidance)",
            "T1583 (Sanction Evasion Procurement via UAE/Turkey/China)",
            "T1592 (Target Reconnaissance for Substation Vulnerabilities)"
        ],
        "regex": r"(альбатрос|алабуга|alabuga|флоров|спиридонов|dolphin 632|комета-м|kometa-m|бампер|моторний човен)"
    },
    "Unit-20924-Kolomna": {
        "aliases": ["924-й ДЦ БпЛА", "в/ч 20924", "Група Кашан", "Соколине полювання"],
        "target_sectors": ["strike_planning", "operator_training", "suicide_drone_operations"],
        "malware": ["shahed-136", "mohajer-6", "orlan-10"],
        "tactics": [
            "T1059 (Custom Mission Flight Planner & Waypoint Generation)",
            "T1584 (Deployment from Roaming Launch Sites Navlya/Tsymbulovo)"
        ],
        "regex": r"(20924|коломейцев|коломєйцев|степовой|глухов|созинов|пивкин|півкін|аеродром кашан|соколине полювання)"
    },
    "Unit-92154-Senezh": {
        "aliases": ["322-й центр СпП Сенеж", "в/ч 92154", "Кодер", "Солнечногорськ"],
        "target_sectors": ["cyber_recon", "ew_bypass", "special_operations"],
        "malware": ["custom_ew_patch", "anti_spoofing_firmware"],
        "tactics": [
            "T1588.003 (Specialized Firmware for EW Navigation Bypass)",
            "T1027 (Obfuscated/Encrypted Telemetry Channels)"
        ],
        "regex": r"(92154|сенеж|senezh|кузнецов дмитрий|кузнєцов дмитро|\bкодер\b)"
    },
    "Unit-35535-448RBR": {
        "aliases": ["448-ма ракетна бригада", "в/ч 35535", "Позивний Сармат", "с. Клюква"],
        "target_sectors": ["ballistic_missile_strikes", "iskander-m", "urban_bombardment"],
        "malware": ["iskander-m", "kn-23", "9m723"],
        "tactics": [
            "T1485 (Kinetic Double-Tap Ballistic Strikes)",
            "T1584 (Roaming Mobile Launchers / 12min Setup Time)"
        ],
        "regex": r"(35535|448-ма|448 ракетн|воробьев александр|воробйов олександр|\bсармат\b)"
    }
}


def analyze_threat_actors(text: str) -> Dict[str, Any]:
    """
    Scans intelligence texts for APT group activities, malware names, and TTP matches.
    Returns matched groups, identified TTPs, and threat severity.
    """
    if not text:
        return {"matched": False, "groups": [], "ttps": [], "threat_level": "NONE"}

    text_lower = text.lower()
    matched_groups = []
    collected_ttps = []

    for group_name, profile in APT_SIGNATURE_DB.items():
        # Check malware and alias regex
        if re.search(profile["regex"], text_lower, re.IGNORECASE):
            matched_groups.append({
                "group": group_name,
                "aliases": profile["aliases"],
                "targets": profile["target_sectors"]
            })
            collected_ttps.extend(profile["tactics"])
        else:
            # Check individual malware signatures
            for m in profile["malware"]:
                if m in text_lower:
                    matched_groups.append({
                        "group": group_name,
                        "detected_malware": m,
                        "targets": profile["target_sectors"]
                    })
                    collected_ttps.extend(profile["tactics"])
                    break

    # Check for Dead Drop Resolver patterns in Telegram
    has_ddr = bool(re.search(r"(t\.me\/[a-zA-Z0-9_]+|github\.com\/[a-zA-Z0-9_\-]+)\s+c2", text_lower))
    if has_ddr:
        collected_ttps.append("T1102.001 (Suspected Telegram / GitHub Dead Drop Resolver)")

    threat_level = "CRITICAL" if len(matched_groups) > 1 or "industroyer" in text_lower else ("HIGH" if matched_groups else "NONE")

    return {
        "matched": len(matched_groups) > 0,
        "threat_level": threat_level,
        "matched_groups": matched_groups,
        "ttps": list(set(collected_ttps)),
        "cyber_kinetic_correlation": any(g["group"] in ["Sandworm", "Gamaredon"] for g in matched_groups)
    }
