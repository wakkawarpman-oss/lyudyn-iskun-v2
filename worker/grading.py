"""
OKINT-PRO · Шар грейдинга розвідданих (Admiralty Code)
Кожен факт несе: надійність джерела (A–F) × достовірність інформації (1–6),
репутацію джерела (байєсівське оновлення за фідбеком аналітика) та composite confidence.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import IntEnum
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
import math


class Reliability(IntEnum):
    """Надійність джерела (Admiralty A–F)."""
    A = 6   # повністю надійне (власний сенсор, верифікований офіційний канал)
    B = 5   # зазвичай надійне (перевірений моніторинг, єРадар, war_monitor)
    C = 4   # доволі надійне (ситуаційні канали)
    D = 3   # зазвичай ненадійне (агрегатори новин, анонімні пабліки)
    E = 2   # ненадійне (сумнівні джерела)
    F = 1   # неможливо оцінити


class Credibility(IntEnum):
    """Достовірність конкретної інформації (1–6)."""
    CONFIRMED = 1        # підтверджено незалежними джерелами / фото / відео
    PROBABLY_TRUE = 2    # узгоджується з іншими фактами / радіолокацією
    POSSIBLY_TRUE = 3    # правдоподібно, але без незалежного підтвердження
    DOUBTFULLY_TRUE = 4  # сумнівно, не узгоджується з траєкторією
    IMPROBABLE = 5       # неправдоподібно, протирічить підтвердженим даним
    CANNOT_JUDGE = 6     # неможливо оцінити достовірність


@dataclass
class IntelFact:
    source_id: str
    reliability: Reliability
    credibility: Credibility
    lat: float
    lon: float
    cep_m: float                       # кругове ймовірне відхилення (метри)
    observed_at: datetime
    topic: str = ""                    # тип події (impact, launch, movement...)
    meta: Dict[str, Any] = field(default_factory=dict)


def _norm(v: int) -> float:
    return (v - 1) / 5.0               # 0..1


def fact_confidence(f: IntelFact, reputation: float) -> float:
    """Composite confidence одного факту: рівновага якості джерела (40%),
    достовірності свідчення (35%) та накопиченої репутації (25%)."""
    base = 0.40 * _norm(int(f.reliability)) + 0.35 * (1.0 - _norm(int(f.credibility))) \
           + 0.25 * reputation
    return round(max(0.0, min(1.0, base)), 3)


class SourceReputation:
    """Beta-Bernoulli репутація джерела з часовим розпадом.
    Аналітик тисне ✓/✗ -> alpha/beta оновлюються; старі підтвердження гаснуть."""

    def __init__(self, alpha: float = 2.0, beta: float = 2.0,
                 decay_halflife_days: float = 21.0):
        self.alpha = float(alpha)
        self.beta = float(beta)
        self.halflife = float(decay_halflife_days)
        self._last: Optional[datetime] = None

    def reputation(self) -> float:
        total = self.alpha + self.beta
        return self.alpha / total if total > 0 else 0.5

    def update(self, confirmed: bool, when: Optional[datetime] = None):
        now = when or datetime.now(timezone.utc)
        if self._last is not None:
            days = max(0.0, (now - self._last).total_seconds() / 86400.0)
            lam = 0.5 ** (days / self.halflife)     # розпад до prior 2/2
            self.alpha = 2.0 + (self.alpha - 2.0) * lam
            self.beta  = 2.0 + (self.beta  - 2.0) * lam
        if confirmed:
            self.alpha += 1.0
        else:
            self.beta += 1.0
        self._last = now

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alpha": round(self.alpha, 4),
            "beta": round(self.beta, 4),
            "reputation": round(self.reputation(), 4),
            "halflife_days": self.halflife,
            "last_updated": self._last.isoformat() if self._last else None
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SourceReputation:
        rep = cls(
            alpha=data.get("alpha", 2.0),
            beta=data.get("beta", 2.0),
            decay_halflife_days=data.get("halflife_days", 21.0)
        )
        if data.get("last_updated"):
            try:
                rep._last = datetime.fromisoformat(data["last_updated"])
            except Exception:
                pass
        return rep


def _grade(facts: List[IntelFact], conflicts: int) -> str:
    if not facts:
        return "F6"
    rel = max(f.reliability for f in facts)
    cred = min(int(f.credibility) for f in facts)          # найсильніше свідчення
    letter = chr(ord("A") + 6 - int(rel))
    tag = f"{letter}{cred}"
    return f"{tag}⚠" if conflicts else tag


def fuse_epicenter(facts: List[IntelFact],
                   reputations: Dict[str, SourceReputation],
                   min_conf: float = 0.30) -> Optional[Dict[str, Any]]:
    """Зважений епіцентр групи фактів (мала відстань — плоска апроксимація).
    Вага = confidence / CEP^2. Повертає координати, зведений CEP та конфлікт."""
    usable = []
    for f in facts:
        rep_val = reputations[f.source_id].reputation() if f.source_id in reputations else 0.5
        if fact_confidence(f, rep_val) >= min_conf:
            usable.append(f)

    if not usable:
        return None

    w = []
    for f in usable:
        rep_val = reputations[f.source_id].reputation() if f.source_id in reputations else 0.5
        conf = fact_confidence(f, rep_val)
        cep_clamped = max(f.cep_m, 50.0)
        w.append(conf / (cep_clamped ** 2))

    W = sum(w)
    if W == 0:
        return None

    lat = sum(f.lat * wi for f, wi in zip(usable, w)) / W
    lon = sum(f.lon * wi for f, wi in zip(usable, w)) / W

    # зведене CEP як sqrt(w-варіанси) у метрах
    var = sum(wi * (f.cep_m / 1.1774) ** 2 for f, wi in zip(usable, w)) / W
    cep = 1.1774 * math.sqrt(max(0.0, var))

    # contradiction detection: джерела з confidence>0.5, що відхиляються >2 CEP
    conflicts = 0
    for f, wi in zip(usable, w):
        rep_val = reputations[f.source_id].reputation() if f.source_id in reputations else 0.5
        if fact_confidence(f, rep_val) > 0.5:
            dist_m = math.hypot((f.lat - lat) * 111320.0, (f.lon - lon) * (111320.0 * math.cos(math.radians(lat))))
            if dist_m > 2 * f.cep_m:
                conflicts += 1

    avg_conf = sum(
        fact_confidence(f, reputations[f.source_id].reputation() if f.source_id in reputations else 0.5)
        for f in usable
    ) / len(usable)

    return {
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "cep_m": round(cep, 1),
        "sources": len(usable),
        "conflicts": conflicts,
        "confidence": round(avg_conf, 3),
        "grade": _grade(usable, conflicts),
    }


def map_channel_to_admiralty(channel_name: str, has_media: bool = False, is_official: bool = False) -> tuple[Reliability, Credibility]:
    """Map channel tier and evidence attributes to Admiralty Reliability and Credibility."""
    ch = (channel_name or "").lower().strip()
    if is_official or ch in ("kyivcityofficial", "va_kyiv", "dsns_telegram", "dsns_kyiv_region", "kpszsu"):
        rel = Reliability.A
    elif ch in ("war_monitor", "eradarrua", "monitor_ukr", "ssternenko"):
        rel = Reliability.B
    elif ch in ("kievreal1", "kyivoperat", "kievinfo_kyiv", "kiev_info", "truexakyiv"):
        rel = Reliability.C
    elif ch in ("suspilnechernihiv", "suspilnerivne", "suspilnekherson"):
        rel = Reliability.C
    else:
        rel = Reliability.D

    if is_official or has_media:
        cred = Credibility.CONFIRMED
    elif rel in (Reliability.A, Reliability.B):
        cred = Credibility.PROBABLY_TRUE
    else:
        cred = Credibility.POSSIBLY_TRUE

    return rel, cred
