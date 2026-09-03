import json
import os
import sys

# Add parent dir to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worker.llm_engine import process_with_llm

def get_resonance(text: str, llm_data: dict) -> int:
    is_confirmed = llm_data.get('is_confirmed_incident', False)
    event_type = llm_data.get('event_type', 'general_alert')
    text_lower = text.lower()
    
    base_resonance = 65 if is_confirmed else 35
    if llm_data.get('casualties') is True or any(w in text_lower for w in ['загибл', 'поранен', 'жертв', 'постраждал']):
        base_resonance += 25
    if llm_data.get('damage_level') in ['high', 'critical']:
        base_resonance += 15
    if event_type in ['direct_strike', 'explosion']:
        base_resonance += 15
        
    return min(base_resonance, 100)

def calibrate_resonance_threshold():
    print("🔄 Починаємо калібрування resonance_score...")
    
    dataset = []
    with open("datasets/golden_standard.jsonl", "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                dataset.append(json.loads(line))
                
    print(f"📄 Завантажено {len(dataset)} записів із golden_standard.jsonl")
    
    # Process dataset
    results = []
    for item in dataset:
        text = item["text"]
        llm_data = process_with_llm(text)
        res = get_resonance(text, llm_data)
        results.append((res, item["label"]))
        print(f" - [{res}] {text[:30]}... (Очікувано: {item['label']})")
        
    thresholds = range(10, 85, 5)
    best_f1 = 0
    best_threshold = 0
    
    print("\n📊 Аналіз порогів:")
    for threshold in thresholds:
        tp = fp = tn = fn = 0
        for res, label in results:
            pred = 1 if res >= threshold else 0
            if pred == 1 and label == 1: tp += 1
            elif pred == 1 and label == 0: fp += 1
            elif pred == 0 and label == 0: tn += 1
            elif pred == 0 and label == 1: fn += 1
            
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
        
        print(f" Поріг {threshold:>2}: F1={f1:.3f} | P={precision:.3f} | R={recall:.3f} | TP={tp} FP={fp} TN={tn} FN={fn}")
        
        if f1 > best_f1:
            best_f1 = f1
            best_threshold = threshold

    print(f"\n✅ Оптимальний поріг resonance: {best_threshold} (F1={best_f1:.3f})")
    return best_threshold

if __name__ == "__main__":
    calibrate_resonance_threshold()
