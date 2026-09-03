import json
import os
import sys

# Add parent dir to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worker.llm_engine import rule_based_fallback_parser

def evaluate_on_golden():
    print("🔄 Оцінка regex-правил (fallback parser) на golden_standard.jsonl...")
    
    dataset = []
    with open("datasets/golden_standard.jsonl", "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                dataset.append(json.loads(line))
                
    tp = fp = tn = fn = 0

    for item in dataset:
        text = item["text"]
        result = rule_based_fallback_parser(text)
        
        # Regex checks if it's kyiv region related
        pred = 1 if result and result.get("is_kyiv_region") else 0
        
        # Let's see if regex correctly identified kyiv context
        expected = 1 if item["kyiv_region"] else 0
        
        if pred == 1 and expected == 1: tp += 1
        elif pred == 1 and expected == 0: fp += 1
        elif pred == 0 and expected == 0: tn += 1
        elif pred == 0 and expected == 1: fn += 1
        
        print(f" - [{pred == expected}] Regex: {pred}, Expected: {expected} | {text}")

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    print("\n📊 Результати:")
    print(f"Precision: {precision:.3f}")
    print(f"Recall: {recall:.3f}")
    print(f"F1: {f1:.3f}")

    # Рекомендації
    if recall < 0.85:
        print("⚠️ Додайте більше ключових слів (пропущено реальні події)")
    if precision < 0.90:
        print("⚠️ Зменшіть чутливість regex (багато хибних спрацьовувань)")

    return f1

if __name__ == "__main__":
    evaluate_on_golden()
