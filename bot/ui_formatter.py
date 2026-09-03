"""
Human-Readable UI Formatter Layer for Telegram Bot
Converts internal database state and technical metadata into clear, actionable,
operator- and civilian-friendly intelligence briefings.
"""
import html
import re
from datetime import datetime, timezone
import zoneinfo
from typing import Tuple, Optional
from database.models import DetectedEvent

try:
    KYIV_TZ = zoneinfo.ZoneInfo("Europe/Kyiv")
except Exception:
    KYIV_TZ = timezone.utc


OFFICIAL_CHANNELS = {
    'kpszsu', 'comafua', 'va_kyiv', 'kyivcityofficial', 'dsns_kyiv_region', 
    'dsns_telegram', 'generalstaffzsu', 'mvs_ua', 'operational_command_north'
}


def format_kyiv_time(dt: Optional[datetime]) -> str:
    """Converts a UTC datetime into HH:MM Kyiv time."""
    if not dt:
        return "--:--"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KYIV_TZ).strftime("%H:%M")


def format_source_display(src: Optional[str]) -> str:
    """Formats source name into readable handle or ID."""
    if not src:
        return "невідомо"
    src_clean = str(src).strip()
    if src_clean.replace('-', '').isdigit():
        return f"ID:{src_clean}"
    return f"@{src_clean.lstrip('@')}"


def format_source_link(src: Optional[str], msg_id: Optional[int]) -> str:
    """Generates direct t.me link for source message."""
    if not src:
        return ""
    src_clean = str(src).strip()
    mid = msg_id or 0
    if src_clean.replace('-', '').isdigit():
        clean_id = src_clean.replace('-100', '')
        return f"https://t.me/c/{clean_id}/{mid}"
    return f"https://t.me/{src_clean.lstrip('@')}/{mid}"


def clean_event_snippet(text: Optional[str], max_chars: int = 120) -> str:
    """Removes HTML artifacts, excess whitespace and truncates nicely."""
    if not text:
        return ""
    # Strip HTML tags
    clean = re.sub(r'<[^>]+>', '', text)
    # Strip URL links and excessive symbols
    clean = re.sub(r'https?://\S+', '', clean)
    clean = ' '.join(clean.split()).strip()
    
    if len(clean) > max_chars:
        clean = clean[:max_chars].rstrip() + "..."
    return html.escape(clean)


def format_event_type_human(event_type: Optional[str]) -> str:
    """
    Refined Human Threat Taxonomy:
    Replaces technical/alarmist labels (e.g. 'ПРЯМИЙ УДАР') with precise categories.
    """
    et = (event_type or "other").lower()
    
    labels = {
        "radar_track": "🛸 <b>БпЛА / Повітряна ціль</b>",
        "explosion": "💥 <b>Вибух</b>",
        "direct_strike": "💥 <b>Влучання / Наслідки атаки</b>",
        "shelling": "💣 <b>Обстріл</b>",
        "fire": "🔥 <b>Пожежа</b>",
        "destruction": "🏚️ <b>Руйнування</b>",
        "casualties": "🏥 <b>Постраждалі</b>",
        "air_defense": "🛡️ <b>Робота сил ППО</b>",
        "general_alert": "⚠️ <b>Повітряна загроза</b>",
        "armed_conflict": "⚔️ <b>Бойові дії</b>",
        "other": "⚡ <b>Подія</b>"
    }
    return labels.get(et, f"⚡ <b>{html.escape(et.upper())}</b>")


def format_confirmation_tier(e: DetectedEvent) -> Tuple[str, str]:
    """
    3-Tier Confidence Model (Human Standard):
    1. 🟢 Підтверджено — Офіційне джерело або кілька незалежних моніторів.
    2. 🟡 Повідомляється — Одне джерело (монітор/агрегатор), очікує додаткового підтвердження.
    3. ⚪ Інформація уточнюється — Неповні, попередні або суперечливі дані.
    """
    status = getattr(e, "verification_status", "UNVERIFIED_SINGLE_SOURCE") or "UNVERIFIED_SINGLE_SOURCE"
    count = getattr(e, "sources_count", None) or 1
    src_ch = (getattr(e, "source_channel", "") or "").lower().lstrip('@')
    source_weight = getattr(e, "source_weight", None) or 0.5
    source_tier = getattr(e, "source_tier", None) or "B"
    is_official = getattr(e, "is_official", False) or (src_ch in OFFICIAL_CHANNELS) or (source_tier == 'S') or (status == "OFFICIAL")

    # Tier 1: 🟢 Підтверджено
    if is_official:
        badge = "🟢 <b>Підтверджено</b>"
        explanation = f"інформація надійшла з офіційного джерела ({format_source_display(e.source_channel)})"
        return badge, explanation
    elif status == "VERIFIED" or count >= 2 or source_weight >= 1.2:
        badge = "🟢 <b>Підтверджено</b>"
        explanation = f"підтверджено кількома незалежними джерелами ({count} дж.)"
        return badge, explanation

    # Tier 3: ⚪ Уточнюється
    elif status in ["INVESTIGATING", "PROVISIONAL", "POSSIBLE_IPSO"]:
        badge = "⚪ <b>Інформація уточнюється</b>"
        explanation = "дані з різних джерел наразі уточнюються"
        return badge, explanation

    # Tier 2: 🟡 Повідомляється
    else:
        badge = "🟡 <b>Повідомляється</b>"
        explanation = "наразі є повідомлення лише з одного джерела, потребує уточнення"
        return badge, explanation


def format_human_event_card(idx: int, e: DetectedEvent, show_snippet: bool = True) -> str:
    """
    Renders a clean human-readable event card for Telegram bot listings.
    Format:
    1. Біла Церква · 10:06
       💥 Влучання / Наслідки атаки
       🟢 Підтверджено — інформація надійшла з офіційного джерела (@KyivCityOfficial).
       📝 Повідомляється про наслідки нічної атаки...
       🔗 Першоджерело: @KyivCityOfficial
    """
    time_str = format_kyiv_time(e.detected_at)
    loc = html.escape(e.location_text or "Київ та область")
    type_label = format_event_type_human(e.event_type)
    badge, explanation = format_confirmation_tier(e)
    src_display = format_source_display(e.source_channel)
    src_link = format_source_link(e.source_channel, e.message_id)

    lines = [
        f"<b>{idx}. {loc} · <code>{time_str}</code></b>",
        f"{type_label}",
        f"{badge} — <i>{explanation}.</i>"
    ]

    if show_snippet and e.message_text:
        snippet = clean_event_snippet(e.message_text, 110)
        if snippet:
            lines.append(f"📝 <i>{snippet}</i>")

    if src_link:
        lines.append(f"🔗 <a href='{src_link}'>Першоджерело {src_display}</a>\n")
    else:
        lines.append(f"📡 Першоджерело: {src_display}\n")

    return "\n".join(lines)
