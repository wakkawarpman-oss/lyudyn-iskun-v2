import os
import re
import json
import base64
import logging
import requests
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

GEOSPY_API_KEY = os.getenv("GEOSPY_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


class AIGeolocation:
    """
    Multi-Modal Visual Geolocation Engine.
    Implements a resilient triple-fallback pipeline:
    1. GeoSpy AI (Specialized spatial geolocation)
    2. Google Gemini Vision (High-speed multimodal terrain analysis)
    3. OpenAI GPT-4o-mini Vision (Resilient general vision fallback)
    """

    def analyze_image(self, image_path: str) -> Optional[Dict[str, Any]]:
        if not os.path.exists(image_path):
            return None

        # 1. Primary: GeoSpy AI
        result = self._analyze_geospy(image_path)
        if result:
            result["provider"] = "GeoSpy"
            return result

        # 2. Secondary Fallback: Google Gemini Vision API
        result = self._analyze_gemini(image_path)
        if result:
            result["provider"] = "Gemini Vision"
            return result

        # 3. Tertiary Fallback: OpenAI GPT-4o-mini Vision
        result = self._analyze_openai(image_path)
        if result:
            result["provider"] = "OpenAI Vision"
            return result

        return None

    def _analyze_geospy(self, image_path: str) -> Optional[Dict[str, Any]]:
        if not GEOSPY_API_KEY:
            return None
        try:
            with open(image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')

            resp = requests.post(
                "https://api.geospy.ai/predict",
                headers={"Authorization": f"Bearer {GEOSPY_API_KEY}"},
                json={"image": f"data:image/jpeg;base64,{image_data}"},
                timeout=25
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "predicted_location": data.get("location"),
                    "confidence": data.get("confidence", "medium"),
                    "coordinates": data.get("coordinates")
                }
        except Exception as e:
            logger.warning(f"GeoSpy API error: {e}")
        return None

    def _analyze_gemini(self, image_path: str) -> Optional[Dict[str, Any]]:
        key = GEMINI_API_KEY or os.getenv("GOOGLE_API_KEY")
        if not key:
            return None
        try:
            with open(image_path, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode('utf-8')

            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={key}"
            prompt = (
                "Ви аналітик тактичного GEOINT. Визначте географічне розташування фото в Україні. "
                "Поверніть ТІЛЬКИ JSON об'єкт з полями: "
                "\"predicted_location\" (назва населеного пункту/вулиці/району), "
                "\"coordinates\": [lat, lon] (якщо вдалося визначити, інакше null), "
                "\"confidence\": \"high\" | \"medium\" | \"low\", "
                "\"clues\": \"архітектура, рослинність, знаки або орієнтири\"."
            )

            payload = {
                "contents": [{
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": "image/jpeg", "data": b64_data}}
                    ]
                }],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 300}
            }

            resp = requests.post(url, json=payload, timeout=25)
            if resp.status_code == 200:
                data = resp.json()
                text_out = data["candidates"][0]["content"]["parts"][0]["text"]
                # Extract JSON from markdown fences if present
                clean_json = re.sub(r"```json\s*", "", text_out)
                clean_json = re.sub(r"```", "", clean_json).strip()
                parsed = json.loads(clean_json)
                return {
                    "predicted_location": parsed.get("predicted_location"),
                    "confidence": parsed.get("confidence", "medium"),
                    "coordinates": parsed.get("coordinates"),
                    "clues": parsed.get("clues")
                }
        except Exception as e:
            logger.warning(f"Gemini Vision API error: {e}")
        return None

    def _analyze_openai(self, image_path: str) -> Optional[Dict[str, Any]]:
        if not OPENAI_API_KEY:
            return None
        try:
            with open(image_path, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode('utf-8')

            url = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            }
            prompt = (
                "Ви аналітик GEOINT. Проаналізуйте фото з України. "
                "Поверніть JSON: {\"predicted_location\": \"місто/район\", \"coordinates\": [lat, lon], \"confidence\": \"high\"|\"medium\"|\"low\"}"
            )

            payload = {
                "model": "gpt-4o-mini",
                "response_format": {"type": "json_object"},
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_data}"}}
                    ]
                }],
                "max_tokens": 200,
                "temperature": 0.1
            }

            resp = requests.post(url, headers=headers, json=payload, timeout=25)
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                return {
                    "predicted_location": parsed.get("predicted_location"),
                    "confidence": parsed.get("confidence", "medium"),
                    "coordinates": parsed.get("coordinates")
                }
        except Exception as e:
            logger.warning(f"OpenAI Vision API error: {e}")
        return None


ai_geo = AIGeolocation()
