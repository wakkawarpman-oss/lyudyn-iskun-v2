import os
import base64
import requests

GEOSPY_API_KEY = os.getenv("GEOSPY_API_KEY")

class AIGeolocation:
    def analyze_image(self, image_path: str):
        if not GEOSPY_API_KEY:
            return None
        try:
            with open(image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')
            
            resp = requests.post(
                "https://api.geospy.ai/predict",
                headers={"Authorization": f"Bearer {GEOSPY_API_KEY}"},
                json={"image": f"data:image/jpeg;base64,{image_data}"},
                timeout=30
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "predicted_location": data.get("location"),
                    "confidence": data.get("confidence"),
                    "coordinates": data.get("coordinates")
                }
        except Exception as e:
            print(f"GeoSpy Error: {e}")
        return None

ai_geo = AIGeolocation()
