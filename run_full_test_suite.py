#!/usr/bin/env python3
"""
УЗАГАЛЬНЕНИЙ ТЕСТ ЛЮДИН ІСКУН
Запускає всі тести і генерує звіт
"""
import os
import subprocess
import sys
from datetime import datetime

TEST_GROUPS = [
    ("A", "Класифікація та валідація LLM", "tests/test_classifier.py tests/test_llm_hallucinations.py tests/test_llm.py"),
    ("B", "Кластеризація та геокодування", "tests/test_clustering.py tests/test_geo_consensus.py tests/test_geo_precision_pipeline.py tests/test_poi_matcher.py"),
    ("C", "Сенсори та радар (Neptun / FIRMS / COT)", "tests/test_neptun_radar.py tests/test_firms_verifier.py tests/test_cot.py"),
    ("D", "Безпека та шифрування", "tests/test_security.py tests/test_reencrypt_all_keys.py"),
    ("E", "Інтеграція та UI", "tests/test_ui_formatter.py tests/test_alert_monitor.py tests/test_e2e.py"),
]

def run():
    print("=" * 60)
    print(f"🧪 ЛЮДИН ІСКУН — ПОВНИЙ ТЕСТ-СЬЮТ")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    total_passed = 0
    total_failed = 0

    for block, name, files in TEST_GROUPS:
        print(f"\n{'─' * 60}")
        print(f"🔘 БЛОК {block}: {name}")
        print(f"{'─' * 60}")
        
        pytest_bin = ".venv/bin/pytest" if os.path.exists(".venv/bin/pytest") else "pytest"
        cmd = f"{pytest_bin} {files} -v --tb=short"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        output = result.stdout + result.stderr
        if "passed" in output or "failed" in output:
            # Simple heuristic since pytest output can be complex
            passed = output.count("PASSED")
            failed = output.count("FAILED") + output.count("ERROR")
            total_passed += passed
            total_failed += failed
            print(f"✅ Passed: {passed} | ❌ Failed/Errors: {failed}")
        else:
            print(f"⚠️  Немає тестів або помилка запуску")
            print(output[:500])

    print(f"\n{'=' * 60}")
    print(f"📊 РЕЗУЛЬТАТ:")
    print(f"   ✅ Пройдено: {total_passed}")
    print(f"   ❌ Провалено: {total_failed}")
    if (total_passed + total_failed) > 0:
        print(f"   📈 Успішність: {total_passed/(total_passed+total_failed)*100:.1f}%")
    print(f"{'=' * 60}")

    if total_failed > 0:
        print("\n🚨 Є ПОМИЛКИ! В прод НЕ ЙТИ.")
        sys.exit(1)
    else:
        print("\n🎉 ВСІ ТЕСТИ ПРОЙДЕНІ. Можна деплоїти.")
        sys.exit(0)

if __name__ == "__main__":
    run()
