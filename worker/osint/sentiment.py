import logging
import json
from worker.llm_engine import _call_groq_text

logger = logging.getLogger(__name__)

class SentimentAnalyzer:
    """Визначає емоційний стан повідомлень очевидців"""
    def analyze(self, text: str) -> dict:
        if not text:
            return {"score": 3, "label": "нейтрально", "is_panic": False}
            
        prompt = """
        Оціни тональність повідомлення очевидця від 1 до 5:
        1 = паніка, страх, крики (дуже емоційно)
        2 = тривога, занепокоєння
        3 = нейтрально, фактично
        4 = спокій, іронія
        5 = чорний гумор, сарказм
        
        Поверни JSON строго в такому форматі:
        {
            "score": число_від_1_до_5,
            "label": "текстовий_опис_цифри"
        }
        """
        
        try:
            # Використовуємо найшвидшу модель для сентименту
            resp = _call_groq_text(text, prompt, model="openai/gpt-oss-20b")
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                data = json.loads(content)
                score = int(data.get("score", 3))
                label = str(data.get("label", "нейтрально"))
                return {
                    "score": score,
                    "label": label,
                    "is_panic": score <= 2
                }
        except Exception as e:
            logger.error(f"Sentiment analysis failed: {e}")
            
        return {"score": 3, "label": "нейтрально", "is_panic": False}

    def should_boost_alert(self, sentiment: dict) -> bool:
        """Якщо масова паніка — підвищуємо пріоритет"""
        return sentiment.get("is_panic", False)

sentiment_analyzer = SentimentAnalyzer()
