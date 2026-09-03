from database.repository import EventRepository

class AnalyticsService:
    @staticmethod
    def format_analytics_report(hours: int = 24) -> str:
        with EventRepository() as repo:
            events = repo.get_events_last_n_hours(hours=hours)
            total = len(events)
            if total == 0:
                return f"📊 За останні {hours} години подій для аналітики немає."

            avg_res = repo.get_avg_resonance(hours=hours)
            categories = repo.get_event_stats_by_type(hours=hours)

            report = f"📊 **АНАЛІТИКА ЗА {hours} ГОДИН**\n\n"
            report += f"Усього зафіксовано подій: **{total}**\n"
            report += f"Середній індекс резонансу: **{avg_res:.1f}/100**\n\n"
            report += "Розподіл за типами:\n"

            type_emoji = {
                "explosion": "💥",
                "direct_strike": "🎯",
                "fire": "🔥",
                "radar_track": "🛸",
                "general_alert": "📢",
                "armed_conflict": "⚔️"
            }

            for event_type, count in categories:
                emoji = type_emoji.get(event_type, "🔹")
                report += f"{emoji} {event_type}: {count}\n"
                
            report += "\n*Дані очищено від дублікатів (кластеризація)*"
            return report

    @staticmethod
    def format_top_events_report(hours: int = 24, limit: int = 5) -> str:
        with EventRepository() as repo:
            top_events = repo.get_top_events_by_resonance(hours=hours, limit=limit)
            if not top_events:
                return f"🔥 За останні {hours} год значних подій не зафіксовано."

            text = f"🔥 **ТОП-{limit} РЕЗОНАНСНИХ ПОДІЙ ЗА {hours} ГОД**\n\n"
            for idx, e in enumerate(top_events, 1):
                loc = e.location_text or "Київ"
                res = f"{e.resonance_score}/100" if e.resonance_score else "?/100"
                text += f"{idx}. **{loc}** ({res}) — {e.event_type}\n"
                text += f"   _{e.message_text[:60]}..._\n"
            return text
