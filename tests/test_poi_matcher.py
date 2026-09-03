from worker.geo_extractors.poi_matcher import match_poi


def test_match_poi_warehouse_okwine():
    text = "Российские террористы снова бьют по бизнесу в Украине: уничтожены склады OKWINE и «Ласунки», атакован объект..."
    match = match_poi(text)
    assert match is not None
    assert "OKWINE" in match.name
    assert match.category == "warehouse"
    assert match.lat == 50.4536
    assert match.lon == 30.3711
    assert match.precision == "building"


def test_match_poi_logistics_bfk():
    text = "Бориспільський район, Київщина. 3 вересня 2026 року. ₚосійські терористи завдали удару логістичному комплексу «БФК»"
    match = match_poi(text)
    assert match is not None
    assert "БФК" in match.name
    assert match.category == "logistics"
    assert match.lat == 50.3621
    assert match.lon == 30.9315


def test_match_poi_mall_dream_town():
    text = "Вибух біля ТРЦ Дрім Таун на Оболоні"
    match = match_poi(text)
    assert match is not None
    assert "Dream Town" in match.name
    assert match.category == "mall"


def test_match_poi_bridge():
    text = "Рух через міст Патона перекрито через падіння уламків"
    match = match_poi(text)
    assert match is not None
    assert match.name == "Міст Патона"
    assert match.category == "bridge"


def test_no_poi_match():
    assert match_poi("💥Бучанський р-н - вибухи") is None
    assert match_poi("") is None
