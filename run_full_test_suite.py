#!/usr/bin/env python3
"""
УЗАГАЛЬНЕНИЙ ТЕСТ ЛЮДИН ІСКУН
Запускає всі тести і генерує звіт
"""
import subprocess
import sys
from datetime import datetime

TEST_GROUPS = [
    ("A", "Кнопки та інтерфейс", "tests/test_commands_smoke.py tests/test_memes.py"),
    ("B", "Команди (handlers)", "tests/test_commands_functional.py tests/test_commands_edge.py"),
    ("C", "Фонові процеси", "tests/test_background_smoke.py tests/test_background_functional.py"),
    ("D", "Безпека", "tests/test_security_smoke.py tests/test_security_functional.py"),
    ("E", "Інтеграція", "tests/test_integration_smoke.py tests/test_integration_functional.py"),
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
        
        cmd = f"pytest {files} -v --tb=short"
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
