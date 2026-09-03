from worker.geo_extractors.address_parser import extract_addresses


def test_extract_street_with_inflection():
    text = "Кадри кульмінації конфлікту між СБУ та ГУР на вулиці Шумського у Києві."
    res = extract_addresses(text)
    assert len(res) >= 1
    best = res[0]
    assert "Шумського" in best.street
    assert best.city == "Київ"
    assert best.precision == "street"
    assert best.building is None


def test_extract_highway_and_building():
    text = "На Харківському шосе 121 ледь не вщент згорів автомобіль #Toyota #Prius."
    res = extract_addresses(text)
    assert len(res) >= 1
    best = res[0]
    assert best.street == "Харківське шосе"
    assert best.building == "121"
    assert best.city == "Київ"
    assert best.precision == "address"


def test_extract_avenue_and_district():
    text = "Влучання по проспекту Берестейському, буд. 54 у Шевченківському районі"
    res = extract_addresses(text)
    assert len(res) >= 1
    best = res[0]
    assert "Берестейському" in best.street
    assert best.building == "54"
    assert best.district == "Шевченківський район"
    assert best.city == "Київ"
    assert best.precision == "address"


def test_extract_settlement_street_address():
    text = "Вул. Київська, 15, Бровари - приліт уламків шахеда"
    res = extract_addresses(text)
    assert len(res) >= 1
    best = res[0]
    assert "Київська" in best.street
    assert best.building == "15"
    assert best.city == "Бровари"
    assert best.precision == "address"


def test_empty_or_no_address():
    assert extract_addresses("") == []
    assert extract_addresses("💥Бучанський р-н - вибухи") == []
