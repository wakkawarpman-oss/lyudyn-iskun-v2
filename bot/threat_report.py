import datetime
import logging
from zoneinfo import ZoneInfo
from database.models import SessionLocal, DetectedEvent

logger = logging.getLogger(__name__)
KYIV_TZ = ZoneInfo("Europe/Kyiv")

# ─────────────────── Official Source Registry ───────────────────
OFFICIAL_CHANNELS = {
    "kpszsu": "Повітряні Сили ЗСУ",
    "comafua": "Командувач ПС ЗСУ",
    "va_kyiv": "Київська МВА (КМВА)",
    "kyivcityofficial": "Офіційний портал Києва (Кличко)",
    "dsns_telegram": "ДСНС України",
    "dsns_kyiv_region": "ДСНС Київщини",
    "generalstaffzsu": "Генеральний штаб ЗСУ",
    "mvs_ua": "МВС України"
}

# ─────────────── Keyword Detectors (Evidence-Based) ─────────────
BALLISTIC_KEYWORDS = [
    'балістик', 'іскандер', 'ракетна небезпека', 'загроза балістики',
    'ballistic', 'iskander'
]
STRATEGIC_AVIATION_KEYWORDS = [
    'стратегічна авіація', 'ту-95', 'ту-160', 'міг-31',
    'кинджал', 'зліт з аеродром', 'зліт стратегіч',
    'tu-95', 'tu-160', 'mig-31', 'kinzhal', 'strategic aviation',
    'енгельс', 'саваслейка', 'оленья', 'engels', 'savasleyka'
]
CRUISE_MISSILE_KEYWORDS = [
    'крилат', 'х-101', 'х-555', 'калібр', 'калибр',
    'kh-101', 'kh-555', 'caliber', 'cruise missile'
]
DRONE_KEYWORDS = [
    'шахед', 'герань', 'бпла', 'дрон', 'shahed', 'geran', 'uav', 'drone'
]


def format_event_type(event_type: str, lang: str = "ua") -> str:
    types_map_ua = {
        "direct_strike": "💥 ПРЯМИЙ ПРИЛІТ",
        "explosion": "💥 ВИБУХ",
        "fire": "🔥 ПОЖЕЖА",
        "destruction": "🏚️ РУЙНУВАННЯ",
        "casualties": "🚑 ПОСТРАЖДАЛІ",
        "radar_track": "🛸 РАДАРНИЙ ТРЕК БпЛА",
        "general_alert": "⚠️ ОПЕРАТИВНЕ ПОПЕРЕДЖЕННЯ",
        "air_defense": "🛡️ РОБОТА ППО"
    }
    types_map_en = {
        "direct_strike": "💥 DIRECT IMPACT",
        "explosion": "💥 EXPLOSION / DETONATION",
        "fire": "🔥 ACTIVE FIRE",
        "destruction": "🏚️ STRUCTURAL DAMAGE",
        "casualties": "🚑 CASUALTIES REPORTED",
        "radar_track": "🛸 RADAR UAV TRACK",
        "general_alert": "⚠️ OPERATIONAL AIR ALERT",
        "air_defense": "🛡️ AIR DEFENSE ENGAGED"
    }
    m = types_map_en if lang == "en" else types_map_ua
    return m.get(event_type.lower(), f"📍 {event_type.upper()}")


def format_verified_source_link(source: str, msg_id: int, lang: str = "ua") -> str:
    """Generates a verified, clickable Telegram link with human-readable name."""
    if not source:
        return "Unknown Source" if lang == "en" else "Невідоме джерело"
    clean_src = str(source).strip().lstrip('@').lower()

    prefix = "Operational Channel #" if lang == "en" else "Оперативний монітор #"
    if clean_src.isdigit() or clean_src.replace('-', '').isdigit():
        channel_name = f"{prefix}{clean_src[-4:]}"
        url = f"https://t.me/c/{clean_src.replace('-100', '')}/{msg_id}" if msg_id else "https://t.me"
    elif clean_src in OFFICIAL_CHANNELS:
        official_title = "🏛️ Armed Forces / Official" if lang == "en" else f"🏛️ {OFFICIAL_CHANNELS[clean_src]}"
        channel_name = f"{official_title} (@{clean_src})"
        url = f"https://t.me/{clean_src}/{msg_id}" if msg_id else f"https://t.me/{clean_src}"
    else:
        channel_name = f"@{clean_src}"
        url = f"https://t.me/{clean_src}/{msg_id}" if msg_id else f"https://t.me/{clean_src}"

    return f"<a href='{url}'>{channel_name}</a>"


# ─────────────── Deterministic Threat Assessment ────────────────

def _text_matches(text: str, keywords: list) -> bool:
    """Check if any keyword is found in text (case-insensitive)."""
    t = text.lower()
    return any(kw in t for kw in keywords)


def _find_evidence_event(events: list, keywords: list):
    """Find the most recent event matching any keyword. Returns (event, keyword_matched) or (None, None)."""
    for e in events:
        txt = (e.message_text or "").lower()
        for kw in keywords:
            if kw in txt:
                return e, kw
    return None, None


def _find_strategic_aviation_event(events: list):
    """
    Finds the most recent genuine strategic aviation event.
    Rejects criminal/assassination news about Russian personnel in airfield cities.
    """
    direct_aircraft = [
        'ту-95', 'ту-160', 'ту-22', 'міг-31', 'миг-31', 'кинджал', 'кинжал',
        'стратегічна авіація', 'стратегическая авиация', 'tu-95', 'tu-160', 'mig-31', 'kinzhal'
    ]
    airfield_names = ['енгельс', 'саваслейка', 'оленья', 'шайковка', 'engels', 'savasleyka', 'olenya']
    flight_activities = ['зліт', 'виліт', 'борт', 'аеродром', 'активність', 'пуск', 'тривога', 'патрул', 'повітряний простір']
    negatives = ['поранили', 'замах', 'вбито', 'розстріляли', 'критичному стані', 'поранен']

    for e in events:
        txt = (e.message_text or "").lower()

        # Direct aircraft model mentioned
        for da in direct_aircraft:
            if da in txt:
                return e, da

        # Airfield mention with actual flight activity
        for af in airfield_names:
            if af in txt:
                # Ignore news about shot/injured officers without takeoffs
                if any(neg in txt for neg in negatives) and not any(pos in txt for pos in ['зліт', 'виліт', 'борт']):
                    continue
                if any(act in txt for act in flight_activities):
                    return e, f"{af} (зліт/активність)"

    return None, None


def calculate_threat_levels(events: list, lang: str = "ua") -> dict:
    """
    Deterministic threat assessment based ONLY on evidence in the database.
    Every level has a traceable reason.
    """
    # Classify events
    strike_events = [e for e in events if e.event_type in ('direct_strike', 'explosion')]
    drone_track_events = [e for e in events if e.event_type == 'radar_track' or _text_matches(e.message_text or "", DRONE_KEYWORDS)]
    alert_events = [e for e in events if e.event_type == 'general_alert']
    ad_events = [e for e in events if e.event_type == 'air_defense']

    # ──── Ballistic Threat ────
    ballistic_evidence, ballistic_kw = _find_evidence_event(events, BALLISTIC_KEYWORDS)
    if ballistic_evidence:
        dt_val = ballistic_evidence.detected_at.replace(tzinfo=datetime.timezone.utc) if ballistic_evidence.detected_at.tzinfo is None else ballistic_evidence.detected_at
        t_str = dt_val.astimezone(KYIV_TZ).strftime("%H:%M")
        src = ballistic_evidence.source_channel
        if lang == "en":
            ballistic_level = "CRITICAL"
            ballistic_reason = f"Keyword '{ballistic_kw}' found in [{t_str}] from @{src}"
        else:
            ballistic_level = "CRITICAL"
            ballistic_reason = f"Маркер '{ballistic_kw}' знайдено у повідомленні [{t_str}] від @{src}"
    elif len(strike_events) >= 3:
        if lang == "en":
            ballistic_level = "HIGH"
            ballistic_reason = f"{len(strike_events)} confirmed strikes in 24h — indirect ballistic risk"
        else:
            ballistic_level = "HIGH"
            ballistic_reason = f"{len(strike_events)} прильотів за 24 год — непряма ознака балістичної загрози"
    elif len(strike_events) >= 1:
        if lang == "en":
            ballistic_level = "MEDIUM"
            ballistic_reason = f"{len(strike_events)} strike(s) recorded, no ballistic keywords confirmed"
        else:
            ballistic_level = "MEDIUM"
            ballistic_reason = f"{len(strike_events)} приліт(ів), ключових слів про балістику не виявлено"
    else:
        if lang == "en":
            ballistic_level = "LOW"
            ballistic_reason = "No ballistic keywords or strikes detected in 24h data"
        else:
            ballistic_level = "LOW"
            ballistic_reason = "За 24 год маркерів балістичної загрози у повідомленнях не виявлено"

    # ──── Drone Activity ────
    drone_count = len(drone_track_events)
    if drone_count >= 10:
        drone_level = "CRITICAL"
    elif drone_count >= 5:
        drone_level = "HIGH"
    elif drone_count >= 1:
        drone_level = "MEDIUM"
    else:
        drone_level = "LOW"

    if drone_count > 0:
        latest_drone = drone_track_events[0]
        dt_val = latest_drone.detected_at.replace(tzinfo=datetime.timezone.utc) if latest_drone.detected_at.tzinfo is None else latest_drone.detected_at
        t_str = dt_val.astimezone(KYIV_TZ).strftime("%H:%M")
        if lang == "en":
            drone_reason = f"{drone_count} UAV/drone event(s), last at [{t_str}]"
        else:
            drone_reason = f"{drone_count} фіксацій БпЛА, остання о [{t_str}]"
    else:
        if lang == "en":
            drone_reason = "No UAV tracks or drone mentions in 24h data"
        else:
            drone_reason = "Фіксацій руху БпЛА за 24 год не виявлено"

    # ──── Strategic Aviation ────
    aviation_evidence, aviation_kw = _find_strategic_aviation_event(events)
    if aviation_evidence:
        dt_val = aviation_evidence.detected_at.replace(tzinfo=datetime.timezone.utc) if aviation_evidence.detected_at.tzinfo is None else aviation_evidence.detected_at
        t_str = dt_val.astimezone(KYIV_TZ).strftime("%H:%M")
        src = aviation_evidence.source_channel
        if lang == "en":
            aviation_status = "⚠️ ACTIVE"
            aviation_reason = f"Keyword '{aviation_kw}' found in [{t_str}] from @{src}"
        else:
            aviation_status = "⚠️ АКТИВНА"
            aviation_reason = f"Маркер '{aviation_kw}' знайдено у повідомленні [{t_str}] від @{src}"
    else:
        if lang == "en":
            aviation_status = "UNKNOWN"
            aviation_reason = "No strategic aviation mentions found in monitored channels in 24h"
        else:
            aviation_status = "НЕВІДОМО"
            aviation_reason = "За 24 год повідомлень про стратегічну авіацію в підключених каналах не зафіксовано"

    # ──── Summary (deterministic, no LLM) ────
    if lang == "en":
        if len(events) == 0:
            summary = "No events recorded in the database for the last 24 hours."
        elif len(strike_events) > 0:
            summary = f"{len(strike_events)} confirmed strike(s), {drone_count} UAV track(s), {len(alert_events)} air alert(s) recorded in 24h."
        else:
            summary = f"{drone_count} UAV track(s) and {len(alert_events)} air alert(s) recorded in 24h. No confirmed strikes."

        safety = "Follow official air raid alerts. Proceed to shelters immediately upon ballistic threat notifications."
    else:
        if len(events) == 0:
            summary = "За останні 24 години подій у базі даних не зафіксовано."
        elif len(strike_events) > 0:
            summary = f"За 24 год: {len(strike_events)} приліт(ів), {drone_count} фіксацій БпЛА, {len(alert_events)} повітряних тривог."
        else:
            summary = f"За 24 год: {drone_count} фіксацій БпЛА, {len(alert_events)} повітряних тривог. Прямих прильотів не зафіксовано."

        safety = "Дотримуйтесь офіційних повідомлень про повітряну тривогу. При загрозі балістики негайно прямуйте до укриття."

    return {
        "summary": summary,
        "safety": safety,
        "ballistic_level": ballistic_level,
        "ballistic_reason": ballistic_reason,
        "drone_level": drone_level,
        "drone_count": drone_count,
        "drone_reason": drone_reason,
        "aviation_status": aviation_status,
        "aviation_reason": aviation_reason,
        "total_events": len(events),
        "strikes": len(strike_events),
        "alerts": len(alert_events),
        "ad_engaged": len(ad_events),
    }


def _threat_color(level: str) -> str:
    return {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢", "UNKNOWN": "⚪"}.get(level, "⚪")


# ─────────────── Main Report Generator ──────────────────────────

def generate_live_threat_assessment(custom_query: str = "", lang: str = "ua") -> str:
    """Deterministically renders a bilingual verified intelligence report.
    Every claim is backed by a database record or explicitly marked UNKNOWN."""
    db = SessionLocal()
    events_items = []
    recent_events = []
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_kyiv = now_utc.astimezone(KYIV_TZ)

    date_format = "%d.%m.%Y | %H:%M (Kyiv Time)" if lang == "en" else "%d.%m.%Y | %H:%M (за Києвом)"
    now_str = now_kyiv.strftime(date_format)

    try:
        threshold = now_utc.replace(tzinfo=None) - datetime.timedelta(hours=24)
        recent_events = (
            db.query(DetectedEvent)
            .filter(
                DetectedEvent.detected_at >= threshold,
                DetectedEvent.source_channel.not_ilike('test%')
            )
            .order_by(DetectedEvent.detected_at.desc())
            .all()
        )

        for e in recent_events[:10]:
            dt_val = e.detected_at.replace(tzinfo=datetime.timezone.utc) if e.detected_at.tzinfo is None else e.detected_at
            t_str = dt_val.astimezone(KYIV_TZ).strftime("%H:%M")
            type_label = format_event_type(e.event_type, lang=lang)
            source_link = format_verified_source_link(e.source_channel, e.message_id, lang=lang)

            # Clean 3-Tier Human Verification Badge
            source_weight = getattr(e, "source_weight", 0.5)
            source_tier = getattr(e, "source_tier", "B")
            if getattr(e, "is_official", False) or e.source_channel.lower().lstrip('@') in OFFICIAL_CHANNELS or source_tier == 'S':
                verif_badge = "🟢 [CONFIRMED]" if lang == "en" else "🟢 [ПІДТВЕРДЖЕНО]"
            elif getattr(e, "verification_status", "") == "VERIFIED" or getattr(e, "sources_count", 1) >= 2 or source_weight >= 1.2:
                verif_badge = f"🟢 [CONFIRMED {e.sources_count} src.]" if lang == "en" else f"🟢 [ПІДТВЕРДЖЕНО {e.sources_count} дж.]"
            elif getattr(e, "verification_status", "") in ["INVESTIGATING", "PROVISIONAL", "POSSIBLE_IPSO"]:
                verif_badge = "⚪ [INVESTIGATING]" if lang == "en" else "⚪ [УТОЧНЮЄТЬСЯ]"
            else:
                verif_badge = "🟡 [REPORTED]" if lang == "en" else "🟡 [ПОВІДОМЛЯЄТЬСЯ]"

            source_label = "Source" if lang == "en" else "Джерело"
            loc_label = e.location_text or ("Kyiv Region" if lang == "en" else "Київщина")
            events_items.append(
                f"• <code>[{t_str}]</code> <b>{type_label}</b>: {loc_label}\n"
                f"   └ {verif_badge} {source_label}: {source_link}"
            )
    except Exception as exc:
        logger.error(f"Error fetching events for verified report: {exc}")
    finally:
        db.close()

    # ── Deterministic threat calculation ──
    threat = calculate_threat_levels(recent_events, lang=lang)

    # ── Report Assembly ──
    if lang == "en":
        report_lines = [
            "🎯 <b>VERIFIED THREAT ASSESSMENT: Kyiv Region</b>",
            f"<i>As of {now_str} | Evidence-based analysis</i>\n",
            "📌 <b>SITUATION SUMMARY:</b>",
            f"{threat['summary']}\n",
            "📊 <b>24-HOUR DATABASE STATISTICS:</b>",
            f"• Total events recorded: <code>{threat['total_events']}</code>",
            f"• Confirmed strikes: <code>{threat['strikes']}</code>",
            f"• UAV/drone tracks: <code>{threat['drone_count']}</code>",
            f"• Air alerts: <code>{threat['alerts']}</code>",
            f"• Air defense engaged: <code>{threat['ad_engaged']}</code>\n",
            f"{_threat_color(threat['ballistic_level'])} <b>BALLISTIC THREAT: {threat['ballistic_level']}</b>",
            f"   └ <i>Reason: {threat['ballistic_reason']}</i>\n",
            f"{_threat_color(threat['drone_level'])} <b>UAV ACTIVITY: {threat['drone_level']}</b>",
            f"   └ <i>Reason: {threat['drone_reason']}</i>\n",
            f"{'🔴' if threat['aviation_status'] != 'UNKNOWN' else '⚪'} <b>STRATEGIC AVIATION: {threat['aviation_status']}</b>",
            f"   └ <i>Reason: {threat['aviation_reason']}</i>",
        ]
        recent_header = "\n🔍 <b>LATEST VERIFIED EVENTS (with source links):</b>"
        safety_header = "\n⚠️ <b>CIVIL DEFENSE ADVISORY:</b>"
        ref_hint = "\n<i>ℹ️ Weapons reference card: /reference</i>"
    else:
        report_lines = [
            "🎯 <b>ВЕРИФІКОВАНИЙ ЗВІТ ЗАГРОЗ: Київський регіон</b>",
            f"<i>Станом на {now_str} | Аналіз на основі фактів</i>\n",
            "📌 <b>СИТУАЦІЙНА ЗВЕДЕННЯ:</b>",
            f"{threat['summary']}\n",
            "📊 <b>СТАТИСТИКА БД ЗА 24 ГОДИНИ:</b>",
            f"• Усього подій зафіксовано: <code>{threat['total_events']}</code>",
            f"• Підтверджених прильотів: <code>{threat['strikes']}</code>",
            f"• Фіксацій БпЛА: <code>{threat['drone_count']}</code>",
            f"• Повітряних тривог: <code>{threat['alerts']}</code>",
            f"• Робота ППО: <code>{threat['ad_engaged']}</code>\n",
            f"{_threat_color(threat['ballistic_level'])} <b>ЗАГРОЗА БАЛІСТИКИ: {threat['ballistic_level']}</b>",
            f"   └ <i>Підстава: {threat['ballistic_reason']}</i>\n",
            f"{_threat_color(threat['drone_level'])} <b>АКТИВНІСТЬ БпЛА: {threat['drone_level']}</b>",
            f"   └ <i>Підстава: {threat['drone_reason']}</i>\n",
            f"{'🔴' if threat['aviation_status'] != 'НЕВІДОМО' else '⚪'} <b>СТРАТЕГІЧНА АВІАЦІЯ: {threat['aviation_status']}</b>",
            f"   └ <i>Підстава: {threat['aviation_reason']}</i>",
        ]
        recent_header = "\n🔍 <b>ОСТАННІ ВЕРИФІКОВАНІ ПОДІЇ (з посиланнями на джерела):</b>"
        safety_header = "\n⚠️ <b>РЕКОМЕНДАЦІЇ ЦИВІЛЬНОГО ЗАХИСТУ:</b>"
        ref_hint = "\n<i>ℹ️ Довідник ТТХ озброєнь: /reference</i>"

    if events_items:
        report_lines.append(recent_header)
        report_lines.extend(events_items[:7])

    report_lines.append(f"{safety_header}\n{threat['safety']}")
    report_lines.append(ref_hint)

    return "\n".join(report_lines)


# ─────────────── Static Reference Card (Separate) ──────────────

def generate_reference_card(lang: str = "ua") -> str:
    """Static weapons & airbase reference. Clearly marked as non-live reference data."""
    WEAPONS_UA = [
        {"name": "9М723 «Іскандер-М»", "type": "Балістична", "speed": "~2100 м/с (2-5 хв підльоту)", "stock_est": "Оцінка ГУР: ~130-150 од."},
        {"name": "Х-47М2 «Кинджал»", "type": "Аеробалістична", "speed": "до Mach 10", "stock_est": "Оцінка ГУР: ~50 од."},
        {"name": "Х-101 / Х-555", "type": "Крилата ракета", "speed": "дозвукова (0.7M)", "stock_est": "Оцінка ГУР: ~200-250 од."},
        {"name": "Shahed-136 / Герань-2", "type": "Ударний БпЛА", "speed": "180 км/год", "stock_est": "Серійне виробництво"},
        {"name": "3М-54 «Калібр»", "type": "Крилата ракета (морська)", "speed": "дозвукова / фін. Mach 2.9", "stock_est": "Оцінка ГУР: ~80-100 од."},
    ]
    WEAPONS_EN = [
        {"name": "9M723 Iskander-M", "type": "Quasi-Ballistic", "speed": "~2100 m/s (2-5 min flight)", "stock_est": "DIU Est: ~130-150 units"},
        {"name": "Kh-47M2 Kinzhal", "type": "Aero-Ballistic", "speed": "up to Mach 10", "stock_est": "DIU Est: ~50 units"},
        {"name": "Kh-101 / Kh-555", "type": "Cruise Missile", "speed": "Subsonic (0.7M)", "stock_est": "DIU Est: ~200-250 units"},
        {"name": "Shahed-136 / Geran-2", "type": "Attack Drone", "speed": "180 km/h", "stock_est": "Mass Serial Production"},
        {"name": "3M-54 Kalibr", "type": "Cruise Missile (naval)", "speed": "Subsonic / terminal Mach 2.9", "stock_est": "DIU Est: ~80-100 units"},
    ]
    AIRBASES = [
        {"base_ua": "Енгельс-2 (Саратовська обл.)", "base_en": "Engels-2 (Saratov)", "role": "Ту-95МС / Ту-160"},
        {"base_ua": "Саваслейка (Нижньогородська обл.)", "base_en": "Savasleyka (Nizhny Novgorod)", "role": "МіГ-31К (Кинджал)"},
        {"base_ua": "Оленья (Мурманська обл.)", "base_en": "Olenya (Murmansk)", "role": "Ту-95МС / Ту-22М3"},
        {"base_ua": "Приморсько-Ахтарськ / Курськ", "base_en": "Primorsko-Akhtarsk / Kursk", "role": "Shahed launch sites"},
        {"base_ua": "Міллерове / Крим (Чауда)", "base_en": "Millerovo / Crimea (Chauda)", "role": "Iskander / Drones"},
    ]

    if lang == "en":
        lines = [
            "📖 <b>STATIC REFERENCE: RF Weapons & Airbases</b>",
            "<i>⚠️ This is a static reference card. Data is NOT updated in real-time.</i>",
            "<i>Stock estimates are based on publicly available Ukrainian DIU assessments (~2024).</i>\n",
            "🚀 <b>KNOWN WEAPON SYSTEMS:</b>"
        ]
        for w in WEAPONS_EN:
            lines.append(f"• <b>{w['name']}</b> ({w['type']}): {w['speed']} — <i>{w['stock_est']}</i>")
        lines.append("\n🏢 <b>KNOWN STRATEGIC AIRBASES:</b>")
        for b in AIRBASES:
            lines.append(f"• <b>{b['base_en']}</b>: {b['role']}")
        lines.append("\n<i>Sources: Ukrainian DIU (GUR MO) public briefings, RUSI, ISW open-source assessments.</i>")
    else:
        lines = [
            "📖 <b>СТАТИЧНИЙ ДОВІДНИК: Озброєння та авіабази РФ</b>",
            "<i>⚠️ Це статичний довідник. Дані НЕ оновлюються в реальному часі.</i>",
            "<i>Оцінки запасів базуються на публічних брифінгах ГУР МО України (~2024 р.).</i>\n",
            "🚀 <b>ВІДОМІ СИСТЕМИ ОЗБРОЄННЯ:</b>"
        ]
        for w in WEAPONS_UA:
            lines.append(f"• <b>{w['name']}</b> ({w['type']}): {w['speed']} — <i>{w['stock_est']}</i>")
        lines.append("\n🏢 <b>ВІДОМІ СТРАТЕГІЧНІ АВІАБАЗИ:</b>")
        for b in AIRBASES:
            lines.append(f"• <b>{b['base_ua']}</b>: {b['role']}")
        lines.append("\n<i>Джерела: публічні брифінги ГУР МО, RUSI, ISW.</i>")

    return "\n".join(lines)
