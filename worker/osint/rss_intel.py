import feedparser
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class EnhancedRSSIntel:
    """
    Розширений RSS-агрегатор ЗМІ України.
    Покриває ТОП джерела новин для крос-верифікації.
    """
    SOURCES = {
        "rss_ukrinform": "https://www.ukrinform.ua/rss/rubric-ato",
        "rss_pravda": "https://www.pravda.com.ua/rss/view_mainnews/",
        "rss_censor": "https://censor.net.ua/includes/news_rss.xml",
        "rss_rbc_ua": "https://www.rbc.ua/static/rss/ukrnet.ukr.rss.xml",
        "rss_interfax": "https://interfax.com.ua/news/ato.rss",
        "rss_suspilne": "https://suspilne.media/rss/",
        "rss_nv": "https://nv.ua/rss/all.xml",
    }

    KEYWORDS = [
        "Київ", "обстріл", "вибух", "приліт", "ракета", "дрон", "shahed",
        "бпла", "ппо", "тривога", "пожежа", "уламки",
        "буча", "ірпінь", "бровари", "бориспіль", "вишгород"
    ]

    def fetch_all(self, hours: int = 1) -> list:
        since = datetime.utcnow() - timedelta(hours=hours)
        all_results = []
        
        for source_name, url in self.SOURCES.items():
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:30]:
                    published = self._parse_date(entry)
                    if published and published >= since:
                        title = entry.get("title", "")
                        if self._matches_keywords(title):
                            all_results.append({
                                "source": source_name,
                                "title": title,
                                "link": entry.get("link", ""),
                                "time": published,
                                "summary": entry.get("summary", "")[:500]
                            })
            except Exception as e:
                logger.error(f"RSS error {source_name}: {e}")
        
        # Сортуємо за часом (від новіших до старіших)
        all_results.sort(key=lambda x: x["time"], reverse=True)
        return all_results

    def _parse_date(self, entry) -> datetime:
        for field in ["published_parsed", "updated_parsed", "created_parsed"]:
            val = getattr(entry, field, None)
            if val:
                return datetime(*val[:6])
        return None

    def _matches_keywords(self, text: str) -> bool:
        text_lower = text.lower()
        return any(kw.lower() in text_lower for kw in self.KEYWORDS)

rss_v2 = EnhancedRSSIntel()
