"""
Tactical Districts & Microdistricts Registry for Ukrainian Metropolitan Centers.
Supports 9 Major Cities: Kyiv, Dnipro, Zaporizhzhia, Kharkiv, Lviv, Mykolaiv, Sumy, Odesa, Poltava.
Includes de-communization historical alias mapping, morphology stems, and coordinate centroids.
"""
from typing import Dict, List, Set, Optional, Tuple, Any

# ─── 1. CITIES REGISTRY ───
CITIES_REGISTRY: Dict[str, Dict[str, Any]] = {
    "kyiv": {
        "name": "Київ",
        "genitive": "Києва",
        "icon": "🏛️",
        "center": [50.4501, 30.5234],
        "zoom": 11,
        "threat_profile": "Крилаті ракети (Х-101, Калібр), балістика (Іскандер-М, Кинджал, Циркон), БпЛА Shahed-136/131."
    },
    "dnipro": {
        "name": "Дніпро",
        "genitive": "Дніпра",
        "icon": "🌊",
        "center": [48.4647, 35.0462],
        "zoom": 11,
        "threat_profile": "Балістичні удари (Іскандер-М, РС-26/Орєшнік), Х-22/32, Shahed-136. ПМЗ, Придніпровська ТЕС, мости."
    },
    "zaporizhzhia": {
        "name": "Запоріжжя",
        "genitive": "Запоріжжя",
        "icon": "⚡",
        "center": [47.8388, 35.1396],
        "zoom": 11,
        "threat_profile": "КАБи/УМПК (25–35 км від ЛБЗ), С-300/400 по землі, Іскандер-М. ДніпроГЕС, Мотор Січ, Промзона."
    },
    "kharkiv": {
        "name": "Харків",
        "genitive": "Харкова",
        "icon": "🛡️",
        "center": [49.9935, 36.2304],
        "zoom": 11,
        "threat_profile": "Підліт С-300 40 сек, КАБ-500/1500, УМПБ Д-30СН, Shahed, Торнадо-С. Салтівка, ТЕЦ-3/5, ХТЗ."
    },
    "lviv": {
        "name": "Львів",
        "genitive": "Львова",
        "icon": "🏰",
        "center": [49.8397, 24.0297],
        "zoom": 11,
        "threat_profile": "Х-47М2 Кинджал, Х-101/Калібр, Shahed. Більче-Волицьке ПСГ, ПС 750 кВ, залізничні хаби, ЛДАРЗ."
    },
    "mykolaiv": {
        "name": "Миколаїв",
        "genitive": "Миколаєва",
        "icon": "⚓",
        "center": [46.9750, 31.9946],
        "zoom": 11,
        "threat_profile": "Балістика з ТОТ Криму (Іскандер-М), Shahed через лиман, Онікс. Мости Варварівський/Інгульський, Зоря-Машпроект, порти."
    },
    "sumy": {
        "name": "Суми",
        "genitive": "Сум",
        "icon": "🌲",
        "center": [50.9077, 34.7981],
        "zoom": 12,
        "threat_profile": "Кордон 30 км: КАБи, FPV на оптоволокні, Торнадо-С, Shahed, балістика. Сумихімпром, ПС 330 кВ, ТЕЦ."
    },
    "odesa": {
        "name": "Одеса",
        "genitive": "Одеси",
        "icon": "⛵",
        "center": [46.4825, 30.7233],
        "zoom": 11,
        "threat_profile": "Чорноморський морський напрямок: Онікс (П-800), Іскандер-М, Калібр з моря, надмалі Shahed над водою. Порти Великої Одеси."
    },
    "poltava": {
        "name": "Полтава",
        "genitive": "Полтави",
        "icon": "🌾",
        "center": [49.5883, 34.5514],
        "zoom": 12,
        "threat_profile": "Транзитний коридор БпЛА Shahed, балістика Іскандер-М. 179-й НЦ зв'язку, авіамістечко, ПС 330 кВ, залізничні хаби."
    }
}

# ─── 2. DISTRICTS REGISTRY (By City) ───
DISTRICTS_REGISTRY: Dict[str, Dict[str, Dict[str, Any]]] = {
    "kyiv": {
        "kyiv:shevchenko": {
            "name": "Шевченківський",
            "micro": "Татарка, Лук'янівка, Сирець, Шулявка, Нивки, КПІ, Кудрявець"
        },
        "kyiv:podil": {
            "name": "Подільський",
            "micro": "Поділ, Виноградар, Куренівка, Вітряні Гори, Воздвиженка"
        },
        "kyiv:obolon": {
            "name": "Оболонський",
            "micro": "Оболонь, Мінський масив, Пріорка, Пуща-Водиця"
        },
        "kyiv:pechersk": {
            "name": "Печерський",
            "micro": "Печерськ, Липки, Звіринець, Видубичі, Чорна Гора"
        },
        "kyiv:solomiansk": {
            "name": "Солом'янський",
            "micro": "Солом'янка, Чоколівка, Відрадний, Жуляни, Кардачі, Совки"
        },
        "kyiv:holosiiv": {
            "name": "Голосіївський",
            "micro": "Голосієво, Теремки, Деміївка, Корчувате, Феофанія, Пирогово"
        },
        "kyiv:sviatoshyn": {
            "name": "Святошинський",
            "micro": "Борщагівка, Академмістечко, Біличі, Новобіличі, Святошин"
        },
        "kyiv:darnytsia": {
            "name": "Дарницький",
            "micro": "Позняки, Осокорки, Харківський масив, Бортничі, Червоний Хутір"
        },
        "kyiv:dniprovsk": {
            "name": "Дніпровський",
            "micro": "Русанівка, Березняки, Воскресенка, Лівобережний, ДВРЗ, Райдужний"
        },
        "kyiv:desniansk": {
            "name": "Деснянський",
            "micro": "Троєщина, Лісовий масив, Биківня"
        },
        "kyiv:suburbs": {
            "name": "Передмістя Києва",
            "micro": "Бровари, Буча, Ірпінь, Бориспіль, Вишгород, Васильків, Боярка, Вишневе"
        }
    },

    "dnipro": {
        "dnipro:sobornyi": {
            "name": "Соборний",
            "legacy": "Жовтневий",
            "micro": "Нагірний, Перемога (1-6), Соборна площа, Мандриківка, Сокіл (1-2), Лоцкам'янка"
        },
        "dnipro:shevchenkivskyi": {
            "name": "Шевченківський",
            "legacy": "Бабушкінський",
            "micro": "12-й квартал, Тополя (1-3), Мирний, Корея, просп. Богдана Хмельницького"
        },
        "dnipro:tsentralnyi": {
            "name": "Центральний",
            "legacy": "Кіровський",
            "micro": "Центр, просп. Олександра Поля, пр. Лесі Українки, парк Глоби"
        },
        "dnipro:chechelivskyi": {
            "name": "Чечелівський",
            "legacy": "Красногвардійський",
            "micro": "Чечелівка, Краснопілля, вул. Робоча, Південмаш (ЮМЗ/ПМЗ)"
        },
        "dnipro:novokodatskyi": {
            "name": "Новокодацький",
            "legacy": "Ленінський",
            "micro": "Нові Кодаки, Діївка (1-2), Сухачівка, Західний, Парус (1-2), Покровський, Червоний Камінь"
        },
        "dnipro:samarskyi": {
            "name": "Самарський",
            "micro": "Придніпровськ, Придніпровська ТЕС, Ігрень, Рибальське, Одинківка, Північний, Самара"
        },
        "dnipro:and": {
            "name": "Амур-Нижньодніпровський (АНД)",
            "micro": "Амур, Нижньодніпровськ, Сонячний, Березинка, Лівобережний (1-2), Ломівка (Фрунзенський), Клочко"
        },
        "dnipro:industrialnyi": {
            "name": "Індустріальний",
            "micro": "Лівобережний-3, Калиновський (Клочко-6), Слобожанський проспект, Північний промвузол"
        },
        "dnipro:suburbs": {
            "name": "Передмістя Дніпра",
            "micro": "Слобожанське, Підгородне, Обухівка, Новомосковськ (Самар), Іларіонове, Сурсько-Литовське"
        }
    },

    "zaporizhzhia": {
        "zp:voznesenivskyi": {
            "name": "Вознесенівський",
            "legacy": "Орджонікідзевський",
            "micro": "Центр міста, бул. Шевченка, пл. Фестивальна, Вознесенка, Набережна"
        },
        "zp:dniprovskyi": {
            "name": "Дніпровський",
            "legacy": "Ленінський",
            "micro": "Правий берег, Бородінський, Осипенківський, Верхня Хортиця, ДніпроГЕС"
        },
        "zp:zavodskyi": {
            "name": "Заводський",
            "micro": "Павло-Кічкас, Промзона (Запоріжсталь, Дніпроспецсталь, Коксохім, ЗТМК)"
        },
        "zp:komunarskyi": {
            "name": "Комунарський",
            "micro": "Космос (Космічний мкрн), Піски (Південний мкрн), вокзал Запоріжжя-1"
        },
        "zp:oleksandrivskyi": {
            "name": "Олександрівський",
            "legacy": "Жовтневий",
            "micro": "Старе місто, пл. Волі, вул. Поштова, Набережна, Дубовий Гай"
        },
        "zp:khortytskyi": {
            "name": "Хортицький",
            "micro": "Бабурка (Хортицький масив), острів Хортиця, мости Преображенського"
        },
        "zp:shevchenkivskyi": {
            "name": "Шевченківський",
            "micro": "Військове містечко, Мотор Січ, аеропорт Запоріжжя, Зелений Яр, Леваневського"
        },
        "zp:suburbs": {
            "name": "Передмістя Запоріжжя",
            "micro": "Вільнянськ, Кушугум, Балабине, Малокатеринівка, Розумівка, Біленьке"
        }
    },

    "kharkiv": {
        "kh:shevchenkivskyi": {
            "name": "Шевченківський",
            "legacy": "Дзержинський",
            "micro": "Павлове Поле, Олексіївка, Шатилівка, Держпром, майдан Свободи"
        },
        "kh:kyivskyi": {
            "name": "Київський",
            "micro": "Центр, Велика Данилівка, П'ятихатки, Селище Жуковського, Північна Салтівка (частина), ХАІ"
        },
        "kh:saltivskyi": {
            "name": "Салтівський",
            "legacy": "Московський",
            "micro": "Салтівка (602-й, 656-й, 533-й мкрн), Тюрінка, Сабурова Дача"
        },
        "kh:kholodnohirskyi": {
            "name": "Холодногірський",
            "legacy": "Ленінський",
            "micro": "Холодна Гора, Залютине, Сортувальня, Лиса Гора, Південний вокзал"
        },
        "kh:novobavarskyi": {
            "name": "Новобаварський",
            "legacy": "Жовтневий",
            "micro": "Нова Баварія, Москалівка, Липовий Гай, Лідне, Ледне"
        },
        "kh:osnovianskyi": {
            "name": "Основ'янський",
            "legacy": "Червонозаводський",
            "micro": "Основа, Одеська (вузол), Жихор, проспект Аерокосмічний (Гагаріна)"
        },
        "kh:slobidskyi": {
            "name": "Слобідський",
            "legacy": "Комінтернівський",
            "micro": "Нові Будинки (захід), Селище Артема, стадіон «Металіст»"
        },
        "kh:nemyshlianskyi": {
            "name": "Немишлянський",
            "legacy": "Фрунзенський",
            "micro": "Немишля, Нові Будинки (схід), Кулиничі"
        },
        "kh:industrialnyi": {
            "name": "Індустріальний",
            "legacy": "Орджонікідзевський",
            "micro": "ХТЗ (Тракторний завод), Рогань (Східна/Південна), Горизонт, Східний"
        },
        "kh:suburbs": {
            "name": "Передмістя Харкова",
            "micro": "Чугуїв, Пісочин, Дергачі, Циркуни, Люботин, Мерефа, Безлюдівка, Покотилівка"
        }
    },

    "lviv": {
        "lv:halytskyi": {
            "name": "Галицький",
            "micro": "Історичний Центр, площа Ринок, Цитадель, Погулянка, Снопків"
        },
        "lv:sykhivskyi": {
            "name": "Сихівський",
            "micro": "Сихів (житломасив), Новий Львів, Козельники, Боднарівка, Санта-Барбара"
        },
        "lv:shevchenkivskyi": {
            "name": "Шевченківський",
            "micro": "Замарстинів, Голоско, Збоїща, Рясне-1, Рясне-2, Підзамче"
        },
        "lv:frankivskyi": {
            "name": "Франківський",
            "micro": "Вулька, Кастелівка, Кульпарків, Новий Світ, Привокзальна (південь), Наукова"
        },
        "lv:lychakivskyi": {
            "name": "Личаківський",
            "micro": "Личаків, Кайзервальд, Майорівка, Великі Кривчиці, Винники"
        },
        "lv:zaliznychnyi": {
            "name": "Залізничний",
            "micro": "Левандівка, Білогорща, Скнилівок, Аеропорт Львів, Головний вокзал, ЛДАРЗ"
        },
        "lv:suburbs": {
            "name": "Передмістя Львова",
            "micro": "Винники, Брюховичі, Дубляни, Сокільники, Зимна Водна, Городок, Стрий, Дрогобич"
        }
    },

    "mykolaiv": {
        "mk:tsentralnyi": {
            "name": "Центральний",
            "micro": "Центр міста, Соборна площа, Ракетне Урочище, Соляні, Північний, Тернівка, Варварівка"
        },
        "mk:zavodskyi": {
            "name": "Заводський",
            "micro": "Ліски, Намив, Велика Корениха, Мала Корениха, Чорноморський суднобудівний завод"
        },
        "mk:inhulskyi": {
            "name": "Інгульський",
            "legacy": "Ленінський",
            "micro": "Старий та Новий Водопій, ЮТЗ, Промзона, Сортувальня, ДП «Зоря» — «Машпроект»"
        },
        "mk:korabelnyi": {
            "name": "Корабельний",
            "micro": "Жовтневе, Балабанівка, військовий аеродром «Кульбакине», Завод «Океан», порт «Ольвія»"
        },
        "mk:suburbs": {
            "name": "Передмістя Миколаєва",
            "micro": "Воскресенське, Калинівка, Шевченкове, Галицинове, Очаків"
        }
    },

    "sumy": {
        "sm:kovpakivskyi": {
            "name": "Ковпаківський",
            "micro": "Курський мікрорайон, Веретенівка, Баранівка, Тепличний, Добровільна, Лука, СНВО"
        },
        "sm:zarichnyi": {
            "name": "Зарічний",
            "micro": "Хіммістечко, ПАТ «Сумихімпром», Баси (госпітальний кластер), 9-й та 10-й мкрн, просп. Лушпи, ТЕЦ"
        },
        "sm:suburbs": {
            "name": "Передмістя Сум",
            "micro": "Степанівка, Піщане, Сад, Верхнє Піщане, Хотінь, Краснопілля, Білопілля"
        }
    },

    "odesa": {
        "odesa:peresyp": {
            "name": "Пересипський",
            "legacy": "Суворовський",
            "official_ukr": "Пересипський район",
            "micro": "Селище Котовського (Поскот), Лузанівка, Пересип, Шевченко-3, Ярмаркова, Більшовик, Слобідка Куяльницька"
        },
        "odesa:khadzhybei": {
            "name": "Хаджибейський",
            "legacy": "Малиновський",
            "official_ukr": "Хаджибейський район",
            "micro": "Черемушки (Черьомушки), Молдаванка (частина), Слобідка (лікарні), Ближні/Дальні Млини, Застава-1/2"
        },
        "odesa:prymor": {
            "name": "Приморський",
            "official_ukr": "Приморський район",
            "micro": "Історичний Центр, Молдаванка (схід), Одеський морський порт, Митна площа, Ланжерон, Отрада, Аркадія, Фонтан (1-9 ст.)"
        },
        "odesa:kyivskyi": {
            "name": "Київський",
            "official_ukr": "Київський район",
            "micro": "Житломасив Таїрова (ж/м Таїрова), Вузівський, Фонтан (10-16 ст.), Чорноморка, аеродром «Шкільний», Совіньйон"
        },
        "odesa:suburbs": {
            "name": "Передмістя та Порти",
            "official_ukr": "Передмістя та Порти Великої Одеси",
            "micro": "Чорноморськ (порт), Южне (порт «Південний», ОПЗ), Фонтанка, Крижанівка, Усатове (ПС 750 кВ), Затока (міст)"
        }
    },

    "poltava": {
        "pol:kyivskyi": {
            "name": "Київський",
            "micro": "Центр (північ), Половки, Юрівка, Браїлки, Рибці, 179-й НЦ військ зв'язку, авіамістечко, Полтава-Київська"
        },
        "pol:shevchenkivskyi": {
            "name": "Шевченківський",
            "legacy": "Жовтневий",
            "micro": "Центр (південь), Корпусний сад, Алмазний, Сади-1, Сади-2, Мотель, Боженка"
        },
        "pol:podilskyi": {
            "name": "Подільський",
            "legacy": "Ленінський",
            "micro": "Поділ, Левада (житловий масив), Дублянщина, Крутий Берег, Вороніна, Полтава-Південна"
        },
        "pol:suburbs": {
            "name": "Передмістя Полтави",
            "micro": "Щербані, Розсошенці, Терешки, Супрунівка, Ковалівка, Миргород, Кременчук (НПЗ, ГЕС, КВБЗ)"
        }
    }
}

# Flat District Lookup: district_key -> District Metadata (supports short and long city prefixes)
FLAT_DISTRICTS: Dict[str, Dict[str, Any]] = {}
for city_id, dist_map in DISTRICTS_REGISTRY.items():
    for dist_key, meta in dist_map.items():
        data = {**meta, "city_id": city_id}
        FLAT_DISTRICTS[dist_key] = data
        if ":" in dist_key:
            prefix, dname = dist_key.split(":", 1)
            # Register full city prefix if short was used
            if prefix == "kh":
                FLAT_DISTRICTS[f"kharkiv:{dname}"] = data
            elif prefix == "zp":
                FLAT_DISTRICTS[f"zaporizhzhia:{dname}"] = data
            elif prefix == "lv":
                FLAT_DISTRICTS[f"lviv:{dname}"] = data
            elif prefix == "mk":
                FLAT_DISTRICTS[f"mykolaiv:{dname}"] = data
            elif prefix == "sm":
                FLAT_DISTRICTS[f"sumy:{dname}"] = data
            elif prefix == "pol":
                FLAT_DISTRICTS[f"poltava:{dname}"] = data
            elif prefix == "kyiv":
                FLAT_DISTRICTS[dname] = data
            # Also register short if full was used
            elif prefix == "kharkiv":
                FLAT_DISTRICTS[f"kh:{dname}"] = data
            elif prefix == "zaporizhzhia":
                FLAT_DISTRICTS[f"zp:{dname}"] = data
            elif prefix == "lviv":
                FLAT_DISTRICTS[f"lv:{dname}"] = data
            elif prefix == "mykolaiv":
                FLAT_DISTRICTS[f"mk:{dname}"] = data
            elif prefix == "sumy":
                FLAT_DISTRICTS[f"sm:{dname}"] = data
            elif prefix == "poltava":
                FLAT_DISTRICTS[f"pol:{dname}"] = data

# Legacy Key Aliases to ensure backward compatibility for old Redis subscriptions
LEGACY_DISTRICT_ALIASES: Dict[str, str] = {
    "shevchenko": "kyiv:shevchenko",
    "podil": "kyiv:podil",
    "obolon": "kyiv:obolon",
    "pechersk": "kyiv:pechersk",
    "solomiansk": "kyiv:solomiansk",
    "holosiiv": "kyiv:holosiiv",
    "sviatoshyn": "kyiv:sviatoshyn",
    "darnytsia": "kyiv:darnytsia",
    "dniprovsk": "kyiv:dniprovsk",
    "desniansk": "kyiv:desniansk",
    "suburbs": "kyiv:suburbs"
}

PREFIX_TO_CITY: Dict[str, str] = {
    "kyiv": "kyiv",
    "dnipro": "dnipro",
    "odesa": "odesa",
    "kharkiv": "kharkiv",
    "kh": "kharkiv",
    "zaporizhzhia": "zaporizhzhia",
    "zp": "zaporizhzhia",
    "lviv": "lviv",
    "lv": "lviv",
    "mykolaiv": "mykolaiv",
    "mk": "mykolaiv",
    "sumy": "sumy",
    "sm": "sumy",
    "poltava": "poltava",
    "pol": "poltava",
}

# ─── 3. MORPHOLOGICAL MICRODISTRICT LOOKUP (360+ Stems) ───
# Maps truncated morphological stems (case-insensitive) directly to canonical district IDs
MICRODISTRICT_LOOKUP: Dict[str, List[str]] = {
    # ── КИЇВ ──
    "татарк": ["kyiv:shevchenko", "kyiv:podil"],
    "татарц": ["kyiv:shevchenko", "kyiv:podil"],
    "лук'янів": ["kyiv:shevchenko"],
    "лук'янівц": ["kyiv:shevchenko"],
    "лук’янів": ["kyiv:shevchenko"],
    "луканів": ["kyiv:shevchenko"],
    "сирець": ["kyiv:shevchenko"],
    "сирц": ["kyiv:shevchenko"],
    "шуляв": ["kyiv:shevchenko"],
    "нивк": ["kyiv:shevchenko"],
    "кпі": ["kyiv:shevchenko", "kyiv:solomiansk"],
    "політех": ["kyiv:shevchenko", "kyiv:solomiansk"],
    "кудряв": ["kyiv:shevchenko"],
    "дорогожич": ["kyiv:shevchenko"],
    "поділ": ["kyiv:podil"],
    "виноградар": ["kyiv:podil"],
    "куренів": ["kyiv:podil"],
    "вітрян": ["kyiv:podil"],
    "воздвижен": ["kyiv:podil"],
    "пріорк": ["kyiv:podil", "kyiv:obolon"],
    "оболон": ["kyiv:obolon"],
    "мінськ": ["kyiv:obolon"],
    "пущ": ["kyiv:obolon"],
    "печерськ": ["kyiv:pechersk"],
    "липк": ["kyiv:pechersk"],
    "звіринець": ["kyiv:pechersk"],
    "звіринц": ["kyiv:pechersk"],
    "видубич": ["kyiv:pechersk"],
    "чорна гора": ["kyiv:pechersk"],
    "солом'ян": ["kyiv:solomiansk"],
    "солом’ян": ["kyiv:solomiansk"],
    "соломян": ["kyiv:solomiansk"],
    "чоколів": ["kyiv:solomiansk"],
    "відрадн": ["kyiv:solomiansk"],
    "жулян": ["kyiv:solomiansk"],
    "кардач": ["kyiv:solomiansk"],
    "караваєв": ["kyiv:solomiansk"],
    "совки": ["kyiv:solomiansk"],
    "голосієв": ["kyiv:holosiiv"],
    "голосіїв": ["kyiv:holosiiv"],
    "теремк": ["kyiv:holosiiv"],
    "деміїв": ["kyiv:holosiiv"],
    "корчуват": ["kyiv:holosiiv"],
    "феофані": ["kyiv:holosiiv"],
    "пирогов": ["kyiv:holosiiv"],
    "китаєв": ["kyiv:holosiiv"],
    "борщагів": ["kyiv:sviatoshyn"],
    "академмістеч": ["kyiv:sviatoshyn"],
    "білич": ["kyiv:sviatoshyn"],
    "новобілич": ["kyiv:sviatoshyn"],
    "святошин": ["kyiv:sviatoshyn"],
    "позняк": ["kyiv:darnytsia"],
    "осокорк": ["kyiv:darnytsia"],
    "харківськ": ["kyiv:darnytsia"],
    "бортнич": ["kyiv:darnytsia"],
    "червоний хутір": ["kyiv:darnytsia"],
    "русанів": ["kyiv:dniprovsk"],
    "березняк": ["kyiv:dniprovsk"],
    "воскресен": ["kyiv:dniprovsk"],
    "лівобереж": ["kyiv:dniprovsk"],
    "дврз": ["kyiv:dniprovsk"],
    "райдужн": ["kyiv:dniprovsk"],
    "троєщин": ["kyiv:desniansk"],
    "лісов": ["kyiv:desniansk"],
    "биківн": ["kyiv:desniansk"],
    "бровар": ["kyiv:suburbs"],
    "буч": ["kyiv:suburbs"],
    "ірпін": ["kyiv:suburbs"],
    "бориспіл": ["kyiv:suburbs"],
    "вишгород": ["kyiv:suburbs"],
    "васильків": ["kyiv:suburbs"],
    "боярк": ["kyiv:suburbs"],
    "вишнев": ["kyiv:suburbs"],

    # ── ДНІПРО ──
    "соборн": ["dnipro:sobornyi"],
    "нагірн": ["dnipro:sobornyi"],
    "перемог": ["dnipro:sobornyi"],
    "ж/м перемога": ["dnipro:sobornyi"],
    "мандриків": ["dnipro:sobornyi"],
    "сокіл": ["dnipro:sobornyi"],
    "лоцкам": ["dnipro:sobornyi"],
    "бабушкін": ["dnipro:shevchenkivskyi"],
    "12-й квартал": ["dnipro:shevchenkivskyi", "dnipro:chechelivskyi"],
    "12 квартал": ["dnipro:shevchenkivskyi", "dnipro:chechelivskyi"],
    "топол": ["dnipro:shevchenkivskyi"],
    "мирн": ["dnipro:shevchenkivskyi"],
    "корея": ["dnipro:shevchenkivskyi"],
    "кіровськ": ["dnipro:tsentralnyi"],
    "поля": ["dnipro:tsentralnyi"],
    "парк глоби": ["dnipro:tsentralnyi"],
    "красногвардійськ": ["dnipro:chechelivskyi"],
    "чечелів": ["dnipro:chechelivskyi"],
    "краснопілл": ["dnipro:chechelivskyi"],
    "робоч": ["dnipro:chechelivskyi"],
    "південмаш": ["dnipro:chechelivskyi"],
    "юмз": ["dnipro:chechelivskyi"],
    "пмз": ["dnipro:chechelivskyi"],
    "южмаш": ["dnipro:chechelivskyi"],
    "новодкод": ["dnipro:novokodatskyi"],
    "новокодацьк": ["dnipro:novokodatskyi"],
    "діївка": ["dnipro:novokodatskyi"],
    "сухачівк": ["dnipro:novokodatskyi"],
    "західн": ["dnipro:novokodatskyi"],
    "парус": ["dnipro:novokodatskyi"],
    "покровськ": ["dnipro:novokodatskyi"],
    "комунар": ["dnipro:novokodatskyi"],
    "червоний камін": ["dnipro:novokodatskyi"],
    "красный камень": ["dnipro:novokodatskyi"],
    "самарськ": ["dnipro:samarskyi"],
    "придніпров": ["dnipro:samarskyi"],
    "ігрен": ["dnipro:samarskyi"],
    "рибальськ": ["dnipro:samarskyi"],
    "одинківк": ["dnipro:samarskyi"],
    "анд": ["dnipro:and"],
    "амур": ["dnipro:and"],
    "нижньодніпр": ["dnipro:and"],
    "сонячн": ["dnipro:and"],
    "березинк": ["dnipro:and"],
    "ломівк": ["dnipro:and"],
    "фрунзенськ": ["dnipro:and"],
    "клочко": ["dnipro:and", "dnipro:industrialnyi"],
    "індустріальн": ["dnipro:industrialnyi"],
    "калиновськ": ["dnipro:industrialnyi"],
    "слобожанськ": ["dnipro:industrialnyi", "dnipro:suburbs"],
    "підгородн": ["dnipro:suburbs"],
    "обухівк": ["dnipro:suburbs"],
    "новомосковськ": ["dnipro:suburbs"],
    "самар": ["dnipro:suburbs"],

    # ── ЗАПОРІЖЖЯ ──
    "вознесенівськ": ["zp:voznesenivskyi"],
    "орджонікідз": ["zp:voznesenivskyi"],
    "фестивальн": ["zp:voznesenivskyi"],
    "вознесенк": ["zp:voznesenivskyi"],
    "дніпровськ": ["zp:dniprovskyi"],
    "бородінськ": ["zp:dniprovskyi"],
    "осипенківськ": ["zp:dniprovskyi"],
    "верхня хортиц": ["zp:dniprovskyi"],
    "дніпрогес": ["zp:dniprovskyi"],
    "днепрогэс": ["zp:dniprovskyi"],
    "павло-кічкас": ["zp:zavodskyi"],
    "кічкас": ["zp:zavodskyi"],
    "запоріжстал": ["zp:zavodskyi"],
    "дніпроспецстал": ["zp:zavodskyi"],
    "зтмк": ["zp:zavodskyi"],
    "комунарськ": ["zp:komunarskyi"],
    "космос": ["zp:komunarskyi"],
    "космічн": ["zp:komunarskyi"],
    "піски": ["zp:komunarskyi"],
    "пески": ["zp:komunarskyi"],
    "південний мкрн": ["zp:komunarskyi"],
    "олександрівськ": ["zp:oleksandrivskyi"],
    "дубовий гай": ["zp:oleksandrivskyi"],
    "хортицьк": ["zp:khortytskyi"],
    "бабурк": ["zp:khortytskyi"],
    "хортиц": ["zp:khortytskyi"],
    "мости преображенськ": ["zp:khortytskyi"],
    "мотор січ": ["zp:shevchenkivskyi"],
    "мотор сич": ["zp:shevchenkivskyi"],
    "івченко-прогрес": ["zp:shevchenkivskyi"],
    "зелений яр": ["zp:shevchenkivskyi"],
    "леваневськ": ["zp:shevchenkivskyi"],
    "вільнянськ": ["zp:suburbs"],
    "кушугум": ["zp:suburbs"],
    "балабин": ["zp:suburbs"],

    # ── ХАРКІВ ──
    "павлове пол": ["kh:shevchenkivskyi"],
    "павлово пол": ["kh:shevchenkivskyi"],
    "олексіївк": ["kh:shevchenkivskyi"],
    "алексеевк": ["kh:shevchenkivskyi"],
    "шатилівк": ["kh:shevchenkivskyi"],
    "держпром": ["kh:shevchenkivskyi"],
    "майдан свобод": ["kh:shevchenkivskyi"],
    "велика данилівк": ["kh:kyivskyi"],
    "п'ятихат": ["kh:kyivskyi"],
    "пятихат": ["kh:kyivskyi"],
    "жуковськ": ["kh:kyivskyi"],
    "хаі": ["kh:kyivskyi"],
    "північна салтів": ["kh:kyivskyi", "kh:saltivskyi"],
    "північній салтів": ["kh:kyivskyi", "kh:saltivskyi"],
    "північну салтів": ["kh:kyivskyi", "kh:saltivskyi"],
    "северная салтов": ["kh:kyivskyi", "kh:saltivskyi"],
    "северной салтов": ["kh:kyivskyi", "kh:saltivskyi"],
    "салтів": ["kh:saltivskyi"],
    "салтов": ["kh:saltivskyi"],
    "салтівц": ["kh:saltivskyi"],
    "салтовц": ["kh:saltivskyi"],
    "салтівськ": ["kh:saltivskyi"],
    "салтівк": ["kh:saltivskyi"],
    "салтовк": ["kh:saltivskyi"],
    "602-й мкрн": ["kh:saltivskyi"],
    "602 мкрн": ["kh:saltivskyi"],
    "тюрінк": ["kh:saltivskyi"],
    "сабурова дач": ["kh:saltivskyi"],
    "холодногірськ": ["kh:kholodnohirskyi"],
    "холодна гор": ["kh:kholodnohirskyi"],
    "холодная гор": ["kh:kholodnohirskyi"],
    "залютин": ["kh:kholodnohirskyi"],
    "сортувальн": ["kh:kholodnohirskyi"],
    "лиса гор": ["kh:kholodnohirskyi"],
    "нова баварі": ["kh:novobavarskyi"],
    "новобаварськ": ["kh:novobavarskyi"],
    "москалівк": ["kh:novobavarskyi"],
    "липовий гай": ["kh:novobavarskyi"],
    "основ'янськ": ["kh:osnovianskyi"],
    "основа": ["kh:osnovianskyi"],
    "одеська": ["kh:osnovianskyi", "kh:slobidskyi"],
    "жихор": ["kh:osnovianskyi"],
    "слобідськ": ["kh:slobidskyi"],
    "комінтернівськ": ["kh:slobidskyi"],
    "нові будинк": ["kh:slobidskyi", "kh:nemyshlianskyi"],
    "новые дом": ["kh:slobidskyi", "kh:nemyshlianskyi"],
    "металіст": ["kh:slobidskyi"],
    "немишлянськ": ["kh:nemyshlianskyi"],
    "немишл": ["kh:nemyshlianskyi"],
    "кулинич": ["kh:nemyshlianskyi"],
    "індустріальн": ["kh:industrialnyi"],
    "хтз": ["kh:industrialnyi"],
    "тракторний завод": ["kh:industrialnyi"],
    "роган": ["kh:industrialnyi"],
    "горизонт": ["kh:industrialnyi"],
    "чугуїв": ["kh:suburbs"],
    "пісочин": ["kh:suburbs"],
    "дергач": ["kh:suburbs"],
    "циркун": ["kh:suburbs"],
    "люботин": ["kh:suburbs"],
    "мереф": ["kh:suburbs"],

    # ── ЛЬВІВ ──
    "галицьк": ["lv:halytskyi"],
    "площа ринок": ["lv:halytskyi"],
    "цитадел": ["lv:halytskyi"],
    "погулянк": ["lv:halytskyi"],
    "сихів": ["lv:sykhivskyi"],
    "сихов": ["lv:sykhivskyi"],
    "сыхов": ["lv:sykhivskyi"],
    "новий львів": ["lv:sykhivskyi"],
    "козельник": ["lv:sykhivskyi"],
    "боднарів": ["lv:sykhivskyi"],
    "боднарівк": ["lv:sykhivskyi"],
    "боднарівц": ["lv:sykhivskyi"],
    "санта-барбар": ["lv:sykhivskyi"],
    "замарстинів": ["lv:shevchenkivskyi"],
    "голоско": ["lv:shevchenkivskyi"],
    "збоїщ": ["lv:shevchenkivskyi"],
    "рясн": ["lv:shevchenkivskyi"],
    "рясне": ["lv:shevchenkivskyi"],
    "рясне-1": ["lv:shevchenkivskyi"],
    "рясне-2": ["lv:shevchenkivskyi"],
    "підзамч": ["lv:shevchenkivskyi"],
    "франківськ": ["lv:frankivskyi"],
    "вульк": ["lv:frankivskyi"],
    "кастелівк": ["lv:frankivskyi"],
    "кульпарків": ["lv:frankivskyi"],
    "кульпарков": ["lv:frankivskyi"],
    "личаків": ["lv:lychakivskyi"],
    "личаков": ["lv:lychakivskyi"],
    "кайзервальд": ["lv:lychakivskyi"],
    "майорівк": ["lv:lychakivskyi"],
    "кривчиц": ["lv:lychakivskyi"],
    "винник": ["lv:lychakivskyi", "lv:suburbs"],
    "залізничн": ["lv:zaliznychnyi"],
    "левандівк": ["lv:zaliznychnyi"],
    "білогорщ": ["lv:zaliznychnyi"],
    "скнилів": ["lv:zaliznychnyi"],
    "лдарз": ["lv:zaliznychnyi"],
    "брюхович": ["lv:suburbs"],
    "дублян": ["lv:suburbs"],
    "сокільник": ["lv:suburbs"],
    "стри": ["lv:suburbs"],
    "дрогобич": ["lv:suburbs"],

    # ── МИКОЛАЇВ ──
    "солян": ["mk:tsentralnyi"],
    "ракетне урочищ": ["mk:tsentralnyi"],
    "тернівк": ["mk:tsentralnyi"],
    "матвіївк": ["mk:tsentralnyi"],
    "варварів": ["mk:tsentralnyi"],
    "варваров": ["mk:tsentralnyi"],
    "варварівський міст": ["mk:tsentralnyi"],
    "інгульський міст": ["mk:tsentralnyi"],
    "ліски": ["mk:zavodskyi"],
    "лески": ["mk:zavodskyi"],
    "намив": ["mk:zavodskyi"],
    "корених": ["mk:zavodskyi"],
    "чсз": ["mk:zavodskyi"],
    "інгульськ": ["mk:inhulskyi"],
    "водопій": ["mk:inhulskyi"],
    "ютз": ["mk:inhulskyi"],
    "зоря-машпроект": ["mk:inhulskyi"],
    "зоря машпроект": ["mk:inhulskyi"],
    "корабельн": ["mk:korabelnyi"],
    "балабанівк": ["mk:korabelnyi"],
    "кульбакин": ["mk:korabelnyi"],
    "океан": ["mk:korabelnyi"],
    "ольві": ["mk:korabelnyi"],
    "очаків": ["mk:suburbs"],

    # ── СУМИ ──
    "ковпаківськ": ["sm:kovpakivskyi"],
    "курськ": ["sm:kovpakivskyi"],
    "курская": ["sm:kovpakivskyi"],
    "веретенівк": ["sm:kovpakivskyi"],
    "баранівк": ["sm:kovpakivskyi"],
    "тепличн": ["sm:kovpakivskyi"],
    "добровільн": ["sm:kovpakivskyi"],
    "снво": ["sm:kovpakivskyi"],
    "зарічн": ["sm:zarichnyi"],
    "хіммістеч": ["sm:zarichnyi"],
    "химгородок": ["sm:zarichnyi"],
    "сумихімпром": ["sm:zarichnyi"],
    "баси": ["sm:zarichnyi"],
    "лушп": ["sm:zarichnyi"],
    "еспланад": ["sm:zarichnyi"],
    "степанівк": ["sm:suburbs"],
    "піщан": ["sm:suburbs"],
    "білопілл": ["sm:suburbs"],
    "краснопілл": ["sm:suburbs"],

    # ── ОДЕСА (ОСОБЛИВА УВАГА: ДЕКОМУНІЗАЦІЯ + АЛІАСИ + МОРЕ) ──
    # Пересипський район (кол. Суворовський)
    "пересипськ": ["odesa:peresyp"],
    "пересип": ["odesa:peresyp"],
    "пересып": ["odesa:peresyp"],
    "суворовськ": ["odesa:peresyp"],
    "суворовский": ["odesa:peresyp"],
    "поскот": ["odesa:peresyp"],
    "посєлок котовського": ["odesa:peresyp"],
    "поселок котовского": ["odesa:peresyp"],
    "котовськ": ["odesa:peresyp"],
    "лузанів": ["odesa:peresyp"],
    "лузанівк": ["odesa:peresyp"],
    "лузановк": ["odesa:peresyp"],
    "лузанівц": ["odesa:peresyp"],
    "лузановц": ["odesa:peresyp"],
    "ярмарков": ["odesa:peresyp"],
    "більшовик": ["odesa:peresyp"],
    "добровольськ": ["odesa:peresyp"],
    "семена палія": ["odesa:peresyp"],
    "заболотн": ["odesa:peresyp"],
    "пересипський міст": ["odesa:peresyp"],

    # Хаджибейський район (кол. Малиновський)
    "хаджибейськ": ["odesa:khadzhybei"],
    "хаджибей": ["odesa:khadzhybei"],
    "малиновськ": ["odesa:khadzhybei"],
    "малиновский": ["odesa:khadzhybei"],
    "черемушк": ["odesa:khadzhybei"],
    "черьомушк": ["odesa:khadzhybei"],
    "слобідк": ["odesa:khadzhybei"],
    "слободк": ["odesa:khadzhybei"],
    "слобідц": ["odesa:khadzhybei"],
    "слободц": ["odesa:khadzhybei"],
    "ближні млини": ["odesa:khadzhybei"],
    "дальні млини": ["odesa:khadzhybei"],
    "застава-1": ["odesa:khadzhybei"],
    "застава-2": ["odesa:khadzhybei"],
    "застава 1": ["odesa:khadzhybei"],
    "застава 2": ["odesa:khadzhybei"],
    "генерала петрова": ["odesa:khadzhybei"],
    "філатов": ["odesa:khadzhybei"],
    "космонавт": ["odesa:khadzhybei"],

    # Приморський район
    "приморськ": ["odesa:prymor"],
    "морвокзал": ["odesa:prymor"],
    "одеський порт": ["odesa:prymor"],
    "морський порт": ["odesa:prymor"],
    "митн": ["odesa:prymor"],
    "ланжерон": ["odesa:prymor"],
    "отрада": ["odesa:prymor"],
    "аркаді": ["odesa:prymor"],
    "аркадия": ["odesa:prymor"],
    "французький бульвар": ["odesa:prymor"],
    "дерибасівськ": ["odesa:prymor"],
    "молдаванк": ["odesa:khadzhybei", "odesa:prymor"],
    "молдаванка": ["odesa:khadzhybei", "odesa:prymor"],
    "малий фонтан": ["odesa:prymor"],
    "середній фонтан": ["odesa:prymor"],

    # Київський район Одеси
    "таїров": ["odesa:kyivskyi"],
    "таиров": ["odesa:kyivskyi"],
    "ж/м таїрова": ["odesa:kyivskyi"],
    "вузівськ": ["odesa:kyivskyi"],
    "вузовский": ["odesa:kyivskyi"],
    "великий фонтан": ["odesa:kyivskyi"],
    "фонтан": ["odesa:prymor", "odesa:kyivskyi"],
    "чорноморк": ["odesa:kyivskyi"],
    "люстдорф": ["odesa:kyivskyi"],
    "шкільн": ["odesa:kyivskyi"],
    "школьн": ["odesa:kyivskyi"],
    "совіньйон": ["odesa:kyivskyi", "odesa:suburbs"],
    "совиньон": ["odesa:kyivskyi", "odesa:suburbs"],
    "корольов": ["odesa:kyivskyi"],
    "глушк": ["odesa:kyivskyi"],

    # Передмістя та Порти Одеси
    "чорноморськ": ["odesa:suburbs"],
    "іллічівськ": ["odesa:suburbs"],
    "южне": ["odesa:suburbs"],
    "южний": ["odesa:suburbs"],
    "порт південний": ["odesa:suburbs"],
    "опз": ["odesa:suburbs"],
    "припортовий": ["odesa:suburbs"],
    "фонтанк": ["odesa:suburbs"],
    "крижанівк": ["odesa:suburbs"],
    "усатов": ["odesa:suburbs"],
    "нерубайськ": ["odesa:suburbs"],
    "заток": ["odesa:suburbs"],
    "затока": ["odesa:suburbs"],
    "маяки": ["odesa:suburbs"],
    "авангард": ["odesa:suburbs"],
    "7 кілометр": ["odesa:suburbs"],
    "7 км": ["odesa:suburbs"],

    # ── ПОЛТАВА ──
    "половк": ["pol:kyivskyi"],
    "юрівк": ["pol:kyivskyi"],
    "браїлк": ["pol:kyivskyi"],
    "рибц": ["pol:kyivskyi"],
    "інститут зв'язку": ["pol:kyivskyi"],
    "інститут зв’язку": ["pol:kyivskyi"],
    "179 навчальний": ["pol:kyivskyi"],
    "авіамістеч": ["pol:kyivskyi"],
    "яківц": ["pol:kyivskyi"],
    "полтава-київськ": ["pol:kyivskyi"],
    "корпусний сад": ["pol:shevchenkivskyi"],
    "алмазн": ["pol:shevchenkivskyi"],
    "сади-1": ["pol:shevchenkivskyi"],
    "сади-2": ["pol:shevchenkivskyi"],
    "сади 1": ["pol:shevchenkivskyi"],
    "сади 2": ["pol:shevchenkivskyi"],
    "мотель": ["pol:shevchenkivskyi"],
    "боженк": ["pol:shevchenkivskyi"],
    "левад": ["pol:podilskyi"],
    "дублянщин": ["pol:podilskyi"],
    "крутий берег": ["pol:podilskyi"],
    "полтава-південн": ["pol:podilskyi"],
    "щербан": ["pol:suburbs"],
    "розсошенц": ["pol:suburbs"],
    "терешк": ["pol:suburbs"],
    "кременчук": ["pol:suburbs"],
    "миргород": ["pol:suburbs"]
}

# ─── 4. HELPER FUNCTIONS ───

def resolve_target_districts(text: str, city_hint: Optional[str] = None) -> List[str]:
    """
    Resolves mentions of microdistricts or districts in OSINT text to canonical district IDs.
    Optionally prioritizes or filters by city_hint ('kyiv', 'odesa', etc.).
    Preserves backward compatibility with legacy Kyiv un-prefixed keys ('shevchenko', 'podil')
    and provides cross-alias mapping for city prefixes.
    """
    if not text:
        return []
    text_lower = text.lower()
    matched_districts: Set[str] = set()

    for micro_stem, d_keys in MICRODISTRICT_LOOKUP.items():
        if micro_stem in text_lower:
            for d_key in d_keys:
                if city_hint:
                    d_city = get_city_for_district(d_key)
                    if d_city == city_hint or d_key.startswith(f"{city_hint}:"):
                        matched_districts.add(d_key)
                else:
                    matched_districts.add(d_key)

    # If city_hint was provided but nothing matched that city, fall back to any match
    if city_hint and not matched_districts:
        for micro_stem, d_keys in MICRODISTRICT_LOOKUP.items():
            if micro_stem in text_lower:
                matched_districts.update(d_keys)

    # Cross-alias expansion:
    # 1. Kyiv legacy un-prefixed (e.g. 'podil', 'shevchenko')
    # 2. Short and long city prefixes (kh: <-> kharkiv:, zp: <-> zaporizhzhia:, etc.)
    expanded: Set[str] = set(matched_districts)
    for d in matched_districts:
        if d.startswith("kyiv:"):
            expanded.add(d.split(":", 1)[1])
        elif d.startswith("kh:"):
            expanded.add(f"kharkiv:{d.split(':', 1)[1]}")
        elif d.startswith("kharkiv:"):
            expanded.add(f"kh:{d.split(':', 1)[1]}")
        elif d.startswith("zp:"):
            expanded.add(f"zaporizhzhia:{d.split(':', 1)[1]}")
        elif d.startswith("zaporizhzhia:"):
            expanded.add(f"zp:{d.split(':', 1)[1]}")
        elif d.startswith("lv:"):
            expanded.add(f"lviv:{d.split(':', 1)[1]}")
        elif d.startswith("lviv:"):
            expanded.add(f"lv:{d.split(':', 1)[1]}")
        elif d.startswith("mk:"):
            expanded.add(f"mykolaiv:{d.split(':', 1)[1]}")
        elif d.startswith("mykolaiv:"):
            expanded.add(f"mk:{d.split(':', 1)[1]}")
        elif d.startswith("sm:"):
            expanded.add(f"sumy:{d.split(':', 1)[1]}")
        elif d.startswith("sumy:"):
            expanded.add(f"sm:{d.split(':', 1)[1]}")
        elif d.startswith("pol:"):
            expanded.add(f"poltava:{d.split(':', 1)[1]}")
        elif d.startswith("poltava:"):
            expanded.add(f"pol:{d.split(':', 1)[1]}")

    return sorted(list(expanded))


def normalize_district_key(key: str) -> str:
    """Normalizes legacy un-prefixed keys (e.g. 'shevchenko') to 'kyiv:shevchenko'."""
    if ":" in key:
        return key
    return LEGACY_DISTRICT_ALIASES.get(key, f"kyiv:{key}")


def get_district_info(district_key: str) -> Dict[str, Any]:
    """Retrieves metadata for any district by canonical key (with legacy fallback)."""
    if district_key in FLAT_DISTRICTS:
        return FLAT_DISTRICTS[district_key]
    canon_key = normalize_district_key(district_key)
    if canon_key in FLAT_DISTRICTS:
        return FLAT_DISTRICTS[canon_key]
    # Fallback default
    city_id = get_city_for_district(district_key)
    return {
        "name": district_key.split(":")[-1].capitalize(),
        "micro": "",
        "city_id": city_id
    }


def get_city_for_district(district_key: str) -> str:
    """Extracts city ID from district key."""
    if ":" in district_key:
        prefix = district_key.split(":", 1)[0]
        if prefix in PREFIX_TO_CITY:
            return PREFIX_TO_CITY[prefix]
    info = get_district_info(district_key)
    return info.get("city_id", "kyiv")


def get_district_display_name(district_key: str) -> str:
    """Returns human-readable formatted string: 'Місто — Район'."""
    info = get_district_info(district_key)
    city_id = info.get("city_id", "kyiv")
    city_meta = CITIES_REGISTRY.get(city_id, {"name": city_id.title(), "icon": "📍"})
    dist_name = info.get("name", district_key)
    if "район" in dist_name.lower() or "передмістя" in dist_name.lower():
        return f"{city_meta['icon']} {city_meta['name']}: {dist_name}"
    return f"{city_meta['icon']} {city_meta['name']}: {dist_name} район"
