import pytest
from worker.llm_engine import process_with_llm

HALLUCINATION_TRAPS = [
    ("Вибух у Києві, 5 ракет, оцінка ГУР", ["130-150", "запаси"]),
    ("Повітряна тривога оголошена", ["STANDARD_PATROL"]),
]

@pytest.mark.parametrize("text,forbidden", HALLUCINATION_TRAPS)
def test_no_hallucinated_terms(text, forbidden):
    result = process_with_llm(text, None)
    # Remove short_summary from string representation to avoid false positives (echoing the prompt)
    result.pop("short_summary", None)
    output = str(result).lower()
    for word in forbidden:
        assert word.lower() not in output, f"LLM галюцинує: {word}"

def test_llm_consistency():
    text = "Бахнуло в Бучі, очевидець зняв відео"
    results = []
    for _ in range(2):
        r = process_with_llm(text, None)
        results.append(r.get("event_type"))
    assert len(set(results)) == 1, f"LLM нестабільний: {results}"
