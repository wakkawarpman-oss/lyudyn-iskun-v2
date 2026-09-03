import time
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worker.llm_engine import _call_groq_text, GROQ_API_KEY

def calibrate_groq_rate():
    """Визначає реальний час відповіді та RPM ліміт для Groq API."""
    print("=" * 60)
    print("⚡ КАЛІБРУВАННЯ LLM RATE LIMITER (Groq API)")
    print("=" * 60)
    
    if not GROQ_API_KEY:
        print("❌ GROQ_API_KEY не знайдено в оточенні.")
        return
        
    times = []
    successes = 0
    errors = 0
    
    test_prompt = "Визнач тип події для тексту: 'Вибух у Києві'"
    
    for i in range(10):
        t0 = time.time()
        try:
            resp = _call_groq_text(test_prompt, "Ти аналітик. Поверни json: {\"event_type\": \"explosion\"}")
            elapsed = time.time() - t0
            times.append(elapsed)
            if resp.status_code == 200:
                successes += 1
                print(f"  Запит {i+1:>2}/10: {elapsed:.2f}s [200 OK]")
            else:
                errors += 1
                print(f"  Запит {i+1:>2}/10: {elapsed:.2f}s [HTTP {resp.status_code}]")
        except Exception as e:
            errors += 1
            print(f"  Запит {i+1:>2}/10: Помилка: {e}")
            
    avg_latency = sum(times) / len(times) if times else 0
    max_rpm = int((60.0 / avg_latency) * 0.8) if avg_latency > 0 else 0
    
    print("\n📊 Результати калібрування Groq:")
    print(f"  • Середній час відповіді (Latency): {avg_latency:.2f} сек")
    print(f"  • Успішних запитів: {successes}/10 ({successes*10}%)")
    print(f"  • Рекомендований безпечний RPM поріг: {min(max_rpm, 30)} запитів/хв")
    print("=" * 60)

if __name__ == "__main__":
    calibrate_groq_rate()
