"""
Tactical Optical Reconnaissance Registry (CCTV & DVR Attack Surface).
====================================================================
Seeded from 'REVIEW P0 - CCTV & DVR Attack Surface' and TOT OSINT investigations.
Provides live visual verification points for battle damage assessment (BDA).
"""

from typing import Dict, List, Any

CCTV_NODES_REGISTRY: List[Dict[str, Any]] = [
    {
        "id": "CCTV-TOT-DHK-01",
        "name": "Вузол CCTV Донецьк (Центральний сектор)",
        "city": "Донецьк (ТОТ)",
        "region": "Донецька область",
        "lat": 48.0159,
        "lon": 37.8028,
        "ip": "109.254.195.100",
        "port": 37777,
        "type": "Dahua DVR (TCP/37777)",
        "provider": "AS20590 Donbass Electronic Communications Ltd.",
        "status": "MONITORED",
        "verified_bda": True,
        "dossier": "Магістральний відеореєстратор транспортної розв'язки біля залізничного вокзалу."
    },
    {
        "id": "CCTV-TOT-DHK-02",
        "name": "Вузол CCTV Донецьк (Південний напрямок)",
        "city": "Донецьк (ТОТ)",
        "region": "Донецька область",
        "lat": 47.9890,
        "lon": 37.7850,
        "ip": "185.114.137.18",
        "port": 37777,
        "type": "Dahua DVR (TCP/37777)",
        "provider": "AS204108 S.U.E. DPR Operator of Networks",
        "status": "ACTIVE_STREAM",
        "verified_bda": True,
        "dossier": "Камера зовнішнього спостереження за логістичним хабом окупаційного корпусу."
    },
    {
        "id": "CCTV-TOT-SEV-01",
        "name": "Вузол CCTV Севастополь (Бухта / Порт)",
        "city": "Севастополь (ТОТ Крим)",
        "region": "АР Крим",
        "lat": 44.6166,
        "lon": 33.5254,
        "ip": "46.35.244.179",
        "port": 8080,
        "type": "Hikvision / Dahua Web Panel",
        "provider": "AS35816 Lancom Ltd.",
        "status": "ACTIVE_STREAM",
        "verified_bda": True,
        "dossier": "Оптичний огляд акваторії Південної бухти та стоянок катерів ЧФ РФ."
    },
    {
        "id": "CCTV-TOT-SEV-02",
        "name": "Вузол CCTV Севастополь (Північна сторона)",
        "city": "Севастополь (ТОТ Крим)",
        "region": "АР Крим",
        "lat": 44.6300,
        "lon": 33.5400,
        "ip": "5.149.208.24",
        "port": 37777,
        "type": "Dahua DVR (TCP/37777)",
        "provider": "AS35816 Lancom Ltd.",
        "status": "MONITORED",
        "verified_bda": True,
        "dossier": "Сектор під'їзних шляхів до причалів та складів БК."
    },
    {
        "id": "CCTV-TOT-LGH-01",
        "name": "Вузол CCTV Луганськ (Траса М-04)",
        "city": "Луганськ (ТОТ)",
        "region": "Луганська область",
        "lat": 48.5740,
        "lon": 39.3078,
        "ip": "193.239.27.169",
        "port": 37777,
        "type": "DVR Video Stream",
        "provider": "AS29031 Lugansk Telephone Company LLC",
        "status": "MONITORED",
        "verified_bda": False,
        "dossier": "Контроль пересування військових колон зі сторони КПП Ізварине."
    },
    {
        "id": "CCTV-FRO-KHK-01",
        "name": "Вузол відеоконтролю Харків (Східний сектор)",
        "city": "Харків",
        "region": "Харківська область",
        "lat": 49.9935,
        "lon": 36.2304,
        "ip": "178.165.85.180",
        "port": 8080,
        "type": "Dahua Digest Panel",
        "provider": "Maxnet Telecommunications",
        "status": "ACTIVE_STREAM",
        "verified_bda": True,
        "dossier": "Міська оглядова камера для оперативної фіксації прильотів та наслідків КАБ."
    },
    {
        "id": "CCTV-TOT-ENR-01",
        "name": "Вузол моніторингу Енергодар (Периметр ЗАЕС)",
        "city": "Енергодар (ТОТ)",
        "region": "Запорізька область",
        "lat": 47.4988,
        "lon": 34.6570,
        "ip": "91.228.x.x",
        "port": 554,
        "type": "RTSP Stream (Port 554)",
        "provider": "DvCom / Tavriya Telecom",
        "status": "MONITORED",
        "verified_bda": True,
        "dossier": "Контроль під'їзних доріг та промислової зони станції."
    }
]


def get_cctv_recon_nodes() -> Dict[str, Any]:
    """Returns all mapped optical CCTV reconnaissance and BDA verification nodes."""
    return {
        "status": "success",
        "count": len(CCTV_NODES_REGISTRY),
        "nodes": CCTV_NODES_REGISTRY
    }
