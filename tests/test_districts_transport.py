import pytest
from bot.handlers.districts import KYIV_DISTRICTS, build_districts_keyboard

def test_kyiv_districts_coverage():
    assert "obolon" in KYIV_DISTRICTS
    assert "podil" in KYIV_DISTRICTS
    assert "pechersk" in KYIV_DISTRICTS
    assert "shevchenko" in KYIV_DISTRICTS
    assert len(KYIV_DISTRICTS) >= 10

def test_build_districts_keyboard_rendering():
    selected = {"obolon", "podil"}
    kb = build_districts_keyboard(selected)
    assert kb is not None
    assert len(kb.inline_keyboard) > 0
    # Check that at least one button has a checkmark
    all_buttons = [btn for row in kb.inline_keyboard for btn in row]
    checked_buttons = [btn for btn in all_buttons if "✅" in btn.text]
    assert len(checked_buttons) == 2
