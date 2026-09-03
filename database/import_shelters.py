import json
from geoalchemy2.elements import WKTElement
from database.models import SessionLocal, BombShelter, engine, Base

def import_kyiv_shelters(json_file_path="/tmp/kyiv_shelters.json"):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    
    with open(json_file_path, "r", encoding="utf-8") as f:
        elements = json.load(f)
        
    print(f"Loading {len(elements)} items into PostgreSQL PostGIS...")
    inserted_count = 0
    
    # Clean previous if any
    db.query(BombShelter).delete()
    db.commit()
    
    for item in elements:
        tags = item.get("tags", {})
        lat = item.get("lat") or item.get("center", {}).get("lat")
        lon = item.get("lon") or item.get("center", {}).get("lon")
        
        if not lat or not lon:
            continue
            
        raw_name = tags.get("name:uk") or tags.get("name") or tags.get("description") or tags.get("addr:street")
        street = tags.get("addr:street", "")
        housenumber = tags.get("addr:housenumber", "")
        address = f"{street} {housenumber}".strip() if street else (tags.get("addr:full") or "Київ")
        district = tags.get("addr:district") or tags.get("district") or "Київ"
        
        railway = tags.get("railway")
        amenity = tags.get("amenity")
        building = tags.get("building")
        parking = tags.get("parking")
        
        if railway in ["station", "subway_entrance"] or tags.get("station") == "subway":
            station_name = raw_name or "Метро"
            name = f"🚇 Станція метро «{station_name}»"
            shelter_type = "metro_station"
            capacity = 2500
        elif building == "bunker" or tags.get("shelter_type") == "bomb_shelter":
            name = f"🛡️ Захисна споруда / Бомбосховище ({raw_name or address})"
            shelter_type = "bunker"
            capacity = 350
        elif parking == "underground":
            name = f"🅿️ Підземний паркінг-укриття ({raw_name or address})"
            shelter_type = "underground_parking"
            capacity = 200
        else:
            name = f"🚪 Споруда цивільного захисту ({raw_name or address})"
            shelter_type = "bomb_shelter"
            capacity = 150
            
        geom_wkt = f"POINT({lon} {lat})"
        
        shelter = BombShelter(
            name=name,
            address=address,
            district=district,
            shelter_type=shelter_type,
            capacity=capacity,
            latitude=str(lat),
            longitude=str(lon),
            geom=WKTElement(geom_wkt, srid=4326),
            is_operational=True
        )
        db.add(shelter)
        inserted_count += 1
        
    db.commit()
    db.close()
    print(f"✅ Successfully inserted {inserted_count} Kyiv bomb shelters into PostGIS database!")

if __name__ == "__main__":
    import_kyiv_shelters()
