import re

with open("worker/tasks.py", "r") as f:
    content = f.read()

# Import sentiment analyzer
if "from worker.osint.sentiment import sentiment_analyzer" not in content:
    content = content.replace("from worker.llm_engine import process_with_llm", "from worker.llm_engine import process_with_llm\nfrom worker.osint.sentiment import sentiment_analyzer")

# Inject sentiment analysis
injection = """
        # --- SENTIMENT ANALYSIS ---
        sentiment = sentiment_analyzer.analyze(text)
        if sentiment_analyzer.should_boost_alert(sentiment):
            logger.info(f"Panic detected! Boosting resonance. Score: {sentiment['score']}")
            base_resonance += 25  # Boost critical event threshold
        
        # Add sentiment to the raw_message for debugging
        payload["sentiment"] = sentiment
"""
if "# --- SENTIMENT ANALYSIS ---" not in content:
    content = content.replace("base_resonance = payload.get(\"base_resonance\", 20)", "base_resonance = payload.get(\"base_resonance\", 20)\n" + injection)

with open("worker/tasks.py", "w") as f:
    f.write(content)
