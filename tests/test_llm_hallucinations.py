import json
import pytest
from unittest.mock import patch, MagicMock
from worker.llm_engine import process_with_llm


def _mock_groq_response(json_body: str, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {"choices": [{"message": {"content": json_body}}]}
    return resp


# Clean, well-formed LLM replies containing none of the forbidden fabricated
# details — these mock what a well-behaved model SHOULD return for each input.
HALLUCINATION_TRAPS = [
    (
        "Вибух у Києві, 5 ракет, оцінка ГУР",
        {"is_kyiv_region": True, "is_confirmed_incident": True, "event_type": "explosion",
         "location": "Київ", "short_summary": "Вибух у Києві"},
        ["130-150", "запаси"],
    ),
    (
        "Повітряна тривога оголошена",
        {"is_kyiv_region": True, "is_confirmed_incident": False, "event_type": "general_alert",
         "location": "Київ", "short_summary": "Повітряна тривога"},
        ["STANDARD_PATROL"],
    ),
]


@pytest.mark.parametrize("text,mock_reply,forbidden", HALLUCINATION_TRAPS)
def test_no_hallucinated_terms(text, mock_reply, forbidden):
    """Mocks the Groq HTTP call — without GROQ_API_KEY set (as in this repo's
    default local env), process_with_llm previously always fell through to
    the offline regex parser, so this test never actually exercised the
    JSON-cleaning/validation path it claims to guard.

    Scope: with a mocked response, this verifies clean_and_validate_json_response
    only surfaces the fields present in the model's reply and doesn't fabricate
    forbidden fields/values on its own. It does NOT verify a real LLM never
    hallucinates these terms — that needs a live, keyed model call, out of
    scope here (no API keys/network in this environment).
    """
    with patch("worker.llm_engine.requests.post", return_value=_mock_groq_response(json.dumps(mock_reply))):
        result = process_with_llm(text, None)
    result.pop("short_summary", None)
    output = str(result).lower()
    for word in forbidden:
        assert word.lower() not in output, f"Pipeline surfaced a forbidden term: {word}"


def test_llm_consistency():
    """With the HTTP call mocked to a fixed reply, this checks that our own
    parsing (clean_and_validate_json_response) is deterministic for the same
    input — not that a real LLM is consistent across calls (unverifiable
    without live, keyed model access)."""
    text = "Бахнуло в Бучі, очевидець зняв відео"
    mock_reply = json.dumps({
        "is_kyiv_region": True, "is_confirmed_incident": True, "event_type": "explosion",
        "location": "Буча", "short_summary": "Вибух у Бучі",
    })
    results = []
    for _ in range(2):
        with patch("worker.llm_engine.requests.post", return_value=_mock_groq_response(mock_reply)):
            r = process_with_llm(text, None)
        results.append(r.get("event_type"))
    assert len(set(results)) == 1, f"Parsing нестабільний: {results}"
