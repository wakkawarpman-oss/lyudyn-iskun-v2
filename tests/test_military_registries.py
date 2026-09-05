"""
Unit tests for OSINT Military Units and Launch Sites Registries.
"""
import pytest
from worker.osint.military_units import (
    get_all_military_units,
    get_all_launch_sites,
    find_military_unit,
    find_nearest_launch_site
)


def test_military_units_loaded():
    units = get_all_military_units()
    assert len(units) >= 14
    unit_ids = [u["unit_id"] for u in units]
    assert any("20924" in u for u in unit_ids)
    assert any("92154" in u for u in unit_ids)


def test_launch_sites_loaded():
    sites = get_all_launch_sites()
    assert len(sites) >= 7
    site_names = [s["name"] for s in sites]
    assert any("Чауда" in s for s in site_names)
    assert any("Шахед" in s or "Shahed" in s for s in site_names)


def test_find_military_unit_nlp():
    # Test number lookup
    res1 = find_military_unit("Перехоплено наказ командира в/ч 20924 щодо вильоту")
    assert res1 is not None
    assert "20924" in res1["unit_id"]

    # Test alias lookup
    res2 = find_military_unit("Розрахунок 50-ї бригади Варяг готує запуск FPV")
    assert res2 is not None
    assert "Варяг" in res2["name"]

    # Test Rubikon center lookup
    res3 = find_military_unit("Центр безпілотних систем Рубікон провів випробування")
    assert res3 is not None
    assert "Рубікон" in res3["name"]

    # Test empty or unmatched
    assert find_military_unit("Цивільний облік автотранспорту") is None


def test_find_nearest_launch_site():
    # Near Crimean coast (45.1, 35.7) -> should match Chauda
    site = find_nearest_launch_site(45.1, 35.7, max_dist_km=100.0)
    assert site is not None
    assert "Чауда" in site["name"]
    assert site["distance_km"] < 50.0

    # Near Kursk (51.8, 36.2) -> should match Khalino or Tsymbulovo
    site_kursk = find_nearest_launch_site(51.8, 36.2, max_dist_km=100.0)
    assert site_kursk is not None
    assert "Курськ" in site_kursk["name"]
    assert site_kursk["distance_km"] < 50.0
