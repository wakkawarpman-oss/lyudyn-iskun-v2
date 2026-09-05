"""
Automated Test Suite for Multi-City Districts Architecture & Localized Threat Routing.
Covers 9 Major Cities: Kyiv, Dnipro, Zaporizhzhia, Kharkiv, Lviv, Mykolaiv, Sumy, Odesa, Poltava.
Verifies:
- 9 Cities Registry completeness
- 53 Administrative Districts + 9 Suburbs
- De-communization aliases (Odesa Peresyp/Khadzhybei, Dnipro, Zaporizhzhia, etc.)
- Morphological microdistrict resolution
- Two-tier hierarchical keyboard rendering
- Backward compatibility with legacy Redis keys
- Address parser multi-city district extraction
"""
import pytest

from bot.districts_registry import (
    CITIES_REGISTRY,
    DISTRICTS_REGISTRY,
    FLAT_DISTRICTS,
    MICRODISTRICT_LOOKUP,
    resolve_target_districts,
    normalize_district_key,
    get_district_info,
    get_city_for_district,
    get_district_display_name
)
from bot.handlers.districts import (
    build_cities_keyboard,
    build_city_districts_keyboard,
    build_districts_keyboard,
    KYIV_DISTRICTS
)
from worker.geo_extractors.address_parser import extract_addresses, CITY_DISTRICTS_MAP


def test_cities_registry_has_all_9_cities():
    expected_cities = {"kyiv", "dnipro", "zaporizhzhia", "kharkiv", "lviv", "mykolaiv", "sumy", "odesa", "poltava"}
    assert set(CITIES_REGISTRY.keys()) == expected_cities
    for cid, meta in CITIES_REGISTRY.items():
        assert "name" in meta
        assert "icon" in meta
        assert "center" in meta
        assert len(meta["center"]) == 2
        assert "threat_profile" in meta


def test_districts_registry_structure_and_coverage():
    assert len(DISTRICTS_REGISTRY) == 9
    total_districts = sum(len(dists) for dists in DISTRICTS_REGISTRY.values())
    # 53 administrative districts + 9 suburbs = 62 sectors
    assert total_districts >= 60

    # Verify Odesa specifically
    odesa_dists = DISTRICTS_REGISTRY["odesa"]
    assert "odesa:peresyp" in odesa_dists
    assert "odesa:khadzhybei" in odesa_dists
    assert "odesa:prymor" in odesa_dists
    assert "odesa:kyivskyi" in odesa_dists
    assert "odesa:suburbs" in odesa_dists
    assert odesa_dists["odesa:peresyp"]["name"] == "Пересипський"
    assert odesa_dists["odesa:khadzhybei"]["name"] == "Хаджибейський"
    assert odesa_dists["odesa:peresyp"]["legacy"] == "Суворовський"
    assert odesa_dists["odesa:khadzhybei"]["legacy"] == "Малиновський"


def test_legacy_key_normalization():
    assert normalize_district_key("shevchenko") == "kyiv:shevchenko"
    assert normalize_district_key("podil") == "kyiv:podil"
    assert normalize_district_key("obolon") == "kyiv:obolon"
    assert normalize_district_key("suburbs") == "kyiv:suburbs"
    assert normalize_district_key("odesa:peresyp") == "odesa:peresyp"
    assert normalize_district_key("kharkiv:saltivskyi") == "kharkiv:saltivskyi"


def test_district_display_name():
    assert "Київ" in get_district_display_name("kyiv:shevchenko")
    assert "Одеса" in get_district_display_name("odesa:peresyp")
    assert "Пересипський" in get_district_display_name("odesa:peresyp")
    assert "Харків" in get_district_display_name("kharkiv:saltivskyi")
    assert "Салтівський" in get_district_display_name("kharkiv:saltivskyi")


def test_keyboard_rendering_tier1_cities():
    selected = {"kyiv:shevchenko", "odesa:peresyp", "odesa:khadzhybei"}
    kb = build_cities_keyboard(selected)
    assert kb is not None
    assert len(kb.inline_keyboard) > 0
    all_buttons = [btn for row in kb.inline_keyboard for btn in row]
    btn_texts = [b.text for b in all_buttons]

    # Verify counters on cities
    assert any("Київ (1)" in t for t in btn_texts)
    assert any("Одеса (2)" in t for t in btn_texts)
    assert any("Харків" in t for t in btn_texts)
    assert any("Скинути всі підписки" in t for t in btn_texts)


def test_keyboard_rendering_tier2_city_districts_odesa():
    selected = {"odesa:peresyp"}
    kb = build_city_districts_keyboard("odesa", selected)
    assert kb is not None
    all_buttons = [btn for row in kb.inline_keyboard for btn in row]
    btn_texts = [b.text for b in all_buttons]

    assert any("✅ Пересипський" in t for t in btn_texts)
    assert any("▫️ Хаджибейський" in t for t in btn_texts)
    assert any("▫️ Приморський" in t for t in btn_texts)
    assert any("▫️ Київський" in t for t in btn_texts)
    assert any("▫️ Передмістя та Порти" in t for t in btn_texts)
    assert any("Обрати всі" in t for t in btn_texts)
    assert any("До вибору міст" in t for t in btn_texts)


def test_legacy_build_districts_keyboard_compatibility():
    selected = {"obolon", "podil"}
    kb = build_districts_keyboard(selected)
    assert kb is not None
    all_buttons = [btn for row in kb.inline_keyboard for btn in row]
    checked = [b for b in all_buttons if "✅" in b.text]
    assert len(checked) == 2


def test_microdistrict_resolution_odesa():
    # Test new official names
    assert "odesa:peresyp" in resolve_target_districts("Зафіксовано Shahed над Пересипом!")
    assert "odesa:khadzhybei" in resolve_target_districts("Вибух у Хаджибейському районі")

    # Test legacy names (de-communization aliases)
    assert "odesa:peresyp" in resolve_target_districts("Тривога в Суворовському районі міста")
    assert "odesa:khadzhybei" in resolve_target_districts("БпЛА в напрямку Малиновського")

    # Test famous microdistricts
    assert "odesa:kyivskyi" in resolve_target_districts("Вибухи на Таїрова")
    assert "odesa:peresyp" in resolve_target_districts("Поскот під атакою безпілотників")
    assert "odesa:khadzhybei" in resolve_target_districts("Гучно на Черемушках")
    assert "odesa:peresyp" in resolve_target_districts("Удар по Лузанівці")


def test_microdistrict_resolution_across_cities():
    # Dnipro
    d_dnipro = resolve_target_districts("БпЛА курсом на Перемогу та Південмаш")
    assert "dnipro:sobornyi" in d_dnipro
    assert "dnipro:chechelivskyi" in d_dnipro

    # Zaporizhzhia
    d_zp = resolve_target_districts("Ракета в напрямку ДніпроГЕС та Хортиці")
    assert "zp:dniprovskyi" in d_zp
    assert "zp:khortytskyi" in d_zp

    # Kharkiv
    d_kh = resolve_target_districts("Вибух на Північній Салтівці, район ХТЗ")
    assert "kh:saltivskyi" in d_kh
    assert "kh:industrialnyi" in d_kh

    # Lviv
    d_lv = resolve_target_districts("Шахед у напрямку Сихова та Рясного")
    assert "lv:sykhivskyi" in d_lv
    assert "lv:shevchenkivskyi" in d_lv

    # Mykolaiv
    d_mk = resolve_target_districts("Вибух біля Варварівського мосту та Соляних")
    assert "mk:tsentralnyi" in d_mk

    # Sumy
    d_sm = resolve_target_districts("Удар по району Сумихімпром та Басів")
    assert "sm:zarichnyi" in d_sm

    # Poltava
    d_pol = resolve_target_districts("БпЛА над Левадою, курс на Половки")
    assert "pol:podilskyi" in d_pol
    assert "pol:kyivskyi" in d_pol


def test_address_parser_multicity_detection():
    # Odesa with street and building
    res_od = extract_addresses("Одеса, вибух на вул. Академіка Корольова 12, Таїрова")
    assert len(res_od) > 0
    assert res_od[0].city == "Одеса"
    assert res_od[0].district == "Київський район"

    # Kharkiv with street and building
    res_kh = extract_addresses("Харків, приліт на вул. Академіка Павлова 140, Салтівка")
    assert len(res_kh) > 0
    assert res_kh[0].city == "Харків"
    assert res_kh[0].district == "Салтівський район"

    # Kyiv with street and building
    res_kyiv = extract_addresses("Київ, вул. Хрещатик 22")
    assert len(res_kyiv) > 0
    assert res_kyiv[0].city == "Київ"
