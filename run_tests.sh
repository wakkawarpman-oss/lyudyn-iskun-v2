#!/bin/bash
set -e
echo "🧪 Запуск тестів Людин іскун..."
export DATABASE_URL="sqlite:///:memory:"

echo "1. Unit-тести класифікатора..."
pytest tests/test_classifier.py -v

echo "2. Unit-тести верифікатора..."
pytest tests/test_verifier.py -v

echo "3. Тести на галюцинації LLM..."
pytest tests/test_llm_hallucinations.py -v

echo "✅ Всі критичні тести пройдено!"
pytest tests/test_memes.py -v
pytest tests/test_e2e.py -v
pytest tests/test_security.py -v
