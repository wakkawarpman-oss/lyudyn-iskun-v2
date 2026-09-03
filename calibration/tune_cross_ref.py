import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.models import SessionLocal, DetectedEvent

def calibrate_cross_ref_window():
    """
    Калібрує оптимальне часове вікно (time_window) для кластеризації подій.
    Аналізує реальні часові дельти між повторними повідомленнями з різних джерел.
    """
    print("=" * 60)
    print("⏱️ КАЛІБРУВАННЯ ЧАСОВОГО ВІКНА КРОС-ВЕРИФІКАЦІЇ")
    print("=" * 60)
    
    db = SessionLocal()
    try:
        events = db.query(DetectedEvent).filter(
            DetectedEvent.source_channel.not_ilike('test%'),
            DetectedEvent.detected_at.isnot(None)
        ).order_by(DetectedEvent.detected_at.asc()).all()
        
        print(f"📊 Аналізуємо {len(events)} реальних подій з бази даних...")
        
        if len(events) < 5:
            print("⚠️ Недостатньо даних для статистичного розрахунку. Використовуємо дефолт: 30 хв.")
            return 30
            
        deltas = []
        for i in range(1, len(events)):
            dt1 = events[i-1].detected_at
            dt2 = events[i].detected_at
            if dt1 and dt2:
                diff_min = abs((dt2 - dt1).total_seconds()) / 60.0
                if diff_min <= 180: # Filter outliers > 3 hours
                    deltas.append(diff_min)
                    
        avg_delta = sum(deltas) / len(deltas) if deltas else 30
        deltas.sort()
        median_delta = deltas[len(deltas)//2] if deltas else 30
        p90_delta = deltas[int(len(deltas)*0.9)] if deltas else 30
        
        # Optimal cluster window should encompass 90% of related chatter:
        recommended_window = max(15, min(int(p90_delta), 60))
        
        print("\n📈 Статистика інтервалів між подіями:")
        print(f"  • Середній інтервал: {avg_delta:.1f} хв")
        print(f"  • Медіанний інтервал: {median_delta:.1f} хв")
        print(f"  • 90-й перцентиль (P90): {p90_delta:.1f} хв")
        print(f"  ✅ Рекомендоване вікно крос-референсу: {recommended_window} хв")
        print("=" * 60)
        return recommended_window
        
    finally:
        db.close()

if __name__ == "__main__":
    calibrate_cross_ref_window()
