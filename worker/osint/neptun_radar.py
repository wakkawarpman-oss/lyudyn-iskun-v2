import datetime
import json
import logging
import math
import os
import urllib.request
try:
    import redis
except ImportError:
    redis = None
from typing import Optional

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
NEPTUN_FEED_URL = "https://neptun.in.ua/api/data"
OBLAST_CENTERS = {
    "kyiv_city": (50.4501, 30.5234, 60.0),
    "kyiv_oblast": (50.3500, 30.2000, 130.0),
    "kyiv": (50.4501, 30.5234, 130.0),
    "vinnytsia": (49.2331, 28.4682, 130.0),
    "volyn": (50.7472, 25.3254, 130.0),
    "dnipropetrovsk": (48.4647, 35.0462, 140.0),
    "donetsk": (48.0159, 37.8029, 140.0),
    "zhytomyr": (50.2547, 28.6587, 130.0),
    "zakarpattia": (48.6208, 22.2879, 130.0),
    "zaporizhzhia": (47.8388, 35.1396, 140.0),
    "ivano_frankivsk": (48.9226, 24.7111, 130.0),
    "kirovohrad": (48.5079, 32.2623, 130.0),
    "luhansk": (48.5740, 39.3078, 140.0),
    "lviv": (49.8397, 24.0297, 130.0),
    "mykolaiv": (46.9750, 31.9946, 140.0),
    "odesa": (46.4825, 30.7233, 140.0),
    "poltava": (49.5883, 34.5514, 140.0),
    "rivne": (50.6199, 26.2516, 130.0),
    "sumy": (50.9077, 34.7981, 140.0),
    "ternopil": (49.5535, 25.5948, 130.0),
    "kharkiv": (49.9935, 36.2304, 140.0),
    "kherson": (46.6354, 32.6169, 140.0),
    "khmelnytskyi": (49.4230, 26.9871, 130.0),
    "cherkasy": (49.4444, 32.0598, 130.0),
    "chernivtsi": (48.2921, 25.9358, 130.0),
    "chernihiv": (51.4982, 31.2893, 140.0),
    "crimea": (44.9521, 34.1024, 140.0),
    "sevastopol": (44.6167, 33.5254, 60.0),
}
KYIV_LAT = 50.4501
KYIV_LON = 30.5234
DNIPRO_LAT = 48.4647
DNIPRO_LON = 35.0462
ZAPORIZHZHIA_LAT = 47.8388
ZAPORIZHZHIA_LON = 35.1396

CACHE_KEY = "radar:neptun:live_drones"
CACHE_TTL = 15  # 15 seconds cache


def calculate_distance_km(lat1: float, lon1: float, lat2: float = KYIV_LAT, lon2: float = KYIV_LON) -> float:
    """Haversine distance in km between two GPS coordinates."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 1)


def classify_threat(threat_type: str, text: str) -> tuple[str, str, str]:
    """Classifies raw threat text into (label, color_hex, category)."""
    s = f"{threat_type or ''} {text or ''}".lower()
    if any(k in s for k in ['баліст', 'іскандер', 'кинжал', 'кинджал']):
        return 'Балістична Ракета', '#ff00cc', 'ballistic'
    if any(k in s for k in ['каб', 'керована', 'бомб', 'авіабомб']):
        return 'КАБ / Авіабомба', '#ffaa00', 'kab'
    if any(k in s for k in ['крилат', 'калібр', 'х-101', 'ракет', 'раке', 'missile', 'cruise']):
        return 'Крилата Ракета', '#ff0044', 'missile'
    if any(k in s for k in ['розвід', 'zala', 'supercam', 'орлан']):
        return 'Розвідувальний БПЛА', '#00bfff', 'recon'
    if any(k in s for k in ['shahed', 'шахед', 'бпла', 'дрон', 'герань']):
        return 'БПЛА Shahed', '#ff3366', 'drone'
    return 'Повітряна Ціль', '#ff9900', 'generic'


def angle_diff(b1: float, b2: float) -> float:
    diff = abs(b1 - b2) % 360
    return 360 - diff if diff > 180 else diff


def filter_drones_for_oblast(all_drones: list, oblast: str) -> tuple[list, list]:
    """
    Separates drones into:
    1. direct_drones (within sector boundary or direct radius)
    2. inbound_drones (outside direct radius, but within 160 km with inbound heading or perimeter proximity)
    """
    if not oblast or oblast == "all":
        return all_drones, []

    center_cfg = OBLAST_CENTERS.get(oblast)
    if not center_cfg:
        direct = [d for d in all_drones if oblast in d.get("relevant_oblasts", [])]
        return direct, []

    c_lat, c_lon, direct_r = center_cfg
    from worker.osint.launch_triangulation import calculate_bearing

    direct_drones = []
    inbound_drones = []

    for d in all_drones:
        d_lat = d.get("lat")
        d_lng = d.get("lng")
        if d_lat is None or d_lng is None:
            continue

        dist_km = calculate_distance_km(d_lat, d_lng, c_lat, c_lon)
        is_direct = (dist_km <= direct_r) or (oblast in d.get("relevant_oblasts", []))

        heading = d.get("heading") or 0.0
        bearing_to_center = calculate_bearing(d_lat, d_lng, c_lat, c_lon)
        diff = angle_diff(heading, bearing_to_center)
        speed = d.get("speed_kmh") or 185.0
        eta_min = round((dist_km / speed) * 60) if speed > 0 else 0

        d_copy = dict(d)
        d_copy["distance_to_center_km"] = dist_km
        d_copy["bearing_to_center_deg"] = round(bearing_to_center, 1)
        d_copy["heading_diff_deg"] = round(diff, 1)
        d_copy["eta_to_center_min"] = eta_min

        if is_direct:
            d_copy["is_direct_threat"] = True
            d_copy["is_inbound_threat"] = False
            direct_drones.append(d_copy)
        elif dist_km <= 160.0:
            if diff <= 65.0 or dist_km <= 100.0:
                d_copy["is_direct_threat"] = False
                d_copy["is_inbound_threat"] = True
                inbound_drones.append(d_copy)

    direct_drones.sort(key=lambda x: x.get("distance_to_center_km", 999))
    inbound_drones.sort(key=lambda x: x.get("distance_to_center_km", 999))

    return direct_drones, inbound_drones


def get_live_radar_threats(force_refresh: bool = False, oblast: Optional[str] = None) -> dict:
    """
    Polls the live Neptun tactical feed and returns processed radar tracks.
    Optionally filters by specific oblast.
    """
    raw_json = None
    r = None
    try:
        if redis:
            r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
            if not force_refresh:
                raw_json = r.get(CACHE_KEY)
    except Exception as e:
        logger.warning(f"Redis cache check failed in neptun_radar: {e}")

    if raw_json:
        try:
            cached_res = json.loads(raw_json)
            if oblast and oblast != "all":
                direct_drones, inbound_drones = filter_drones_for_oblast(cached_res.get("drones", []), oblast)
                return {
                    **cached_res,
                    "drones": direct_drones,
                    "inbound_drones": inbound_drones,
                    "count": len(direct_drones),
                    "direct_count": len(direct_drones),
                    "inbound_count": len(inbound_drones),
                    "total_threat_count": len(direct_drones) + len(inbound_drones)
                }
            return {
                **cached_res,
                "inbound_drones": [],
                "direct_count": len(cached_res.get("drones", [])),
                "inbound_count": 0,
                "total_threat_count": len(cached_res.get("drones", []))
            }
        except Exception:
            pass

    # Fetch live from Neptun feed
    req = urllib.request.Request(
        NEPTUN_FEED_URL,
        headers={
            "User-Agent": "OKINT-PRO/2.0 (Tactical Defense Intelligence)",
            "Accept": "application/json",
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"Neptun radar live fetch failed: {e}")
        return {
            "count": 0,
            "kyiv_threat_count": 0,
            "ballistic_threat": False,
            "drones": [],
            "source": "Neptun",
            "status": "offline_fallback",
            "updated": datetime.datetime.utcnow().isoformat() + "Z",
        }

    raw_markers = data.get("markers") or data.get("tracks") or []
    ballistic = bool(data.get("ballistic_threat"))

    drones = []
    oblast_threat_counts = {ob: 0 for ob in OBLAST_CENTERS}

    for m in raw_markers:
        lat = m.get("lat")
        lng = m.get("lng")
        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
            continue

        label, color, category = classify_threat(m.get("threat_type"), m.get("text"))
        dist_kyiv = calculate_distance_km(lat, lng, KYIV_LAT, KYIV_LON)
        dist_dnipro = calculate_distance_km(lat, lng, DNIPRO_LAT, DNIPRO_LON)
        dist_zp = calculate_distance_km(lat, lng, ZAPORIZHZHIA_LAT, ZAPORIZHZHIA_LON)

        # Calculate proximity to each oblast center
        relevant_obs = []
        for ob_code, (c_lat, c_lon, max_d) in OBLAST_CENTERS.items():
            d_km = calculate_distance_km(lat, lng, c_lat, c_lon)
            if d_km <= max_d:
                relevant_obs.append(ob_code)
                oblast_threat_counts[ob_code] = oblast_threat_counts.get(ob_code, 0) + 1

        # Build trail and structured waypoints (last 20 coordinates)
        raw_positions = m.get("positions") or []
        trail = []
        waypoints = []
        if isinstance(raw_positions, list) and raw_positions:
            for idx, p in enumerate(raw_positions[-20:]):
                if isinstance(p, dict) and "lat" in p and "lng" in p:
                    p_lat = float(p["lat"])
                    p_lng = float(p["lng"])
                    trail.append([p_lat, p_lng])
                    waypoints.append({
                        "lat": p_lat,
                        "lng": p_lng,
                        "time": p.get("time") or p.get("date") or m.get("date") or "",
                        "speed_kmh": float(p.get("speed_kmh") or (m.get("speed_kmh") or 185.0)),
                        "source": p.get("source") or "РЛС Нептун",
                        "index": idx
                    })
        if not trail:
            trail = [[float(lat), float(lng)]]
            waypoints = [{
                "lat": float(lat),
                "lng": float(lng),
                "time": m.get("date") or datetime.datetime.utcnow().isoformat() + "Z",
                "speed_kmh": float(m.get("speed_kmh") or 185.0),
                "source": "РЛС Нептун",
                "index": 0
            }]

        heading_val = float(m.get("course_bearing") or 0)
        if heading_val == 0 and len(trail) >= 2:
            from worker.osint.launch_triangulation import calculate_bearing
            heading_val = round(calculate_bearing(trail[-2][0], trail[-2][1], trail[-1][0], trail[-1][1]), 1)

        speed_val = float(m.get("speed_kmh") or m.get("computed_speed_kmh") or (185.0 if category == "drone" else 0))

        # Kalman Track Fusion and ETA Uncertainty Cone
        track_id = str(m.get("id") or m.get("track_id") or f"{lat:.4f}_{lng:.4f}")
        now_ts = datetime.datetime.utcnow().timestamp()
        eta_cone_data = None
        try:
            from worker.track_fusion import KalmanTrackFilter
            kf = KalmanTrackFilter(q_accel=8.0)
            initial_mps = speed_val / 3.6 if speed_val > 0 else 45.0
            state, hist = kf.init_track(
                track_id, lat, lng, now_ts,
                source_type="radar",
                initial_heading_deg=heading_val if heading_val > 0 else None,
                initial_speed_mps=initial_mps
            )
            if len(trail) >= 2:
                step_dt = 15.0
                start_t = now_ts - len(trail) * step_dt
                state, hist = kf.init_track(
                    track_id, trail[0][0], trail[0][1], start_t,
                    source_type="radar",
                    initial_heading_deg=heading_val if heading_val > 0 else None,
                    initial_speed_mps=initial_mps
                )
                for idx, pt in enumerate(trail[1:], start=1):
                    obs_t = start_t + idx * step_dt
                    state = kf.add_measurement(state, hist, lat=pt[0], lon=pt[1], t=obs_t, source_type="radar", source_id="neptun")
                state = kf.add_measurement(state, hist, lat=lat, lon=lng, t=now_ts, source_type="radar", source_id="neptun")
                speed_val = round(state.speed_kmh, 1)
                heading_val = round(state.heading_deg, 1)

            eta_cone_data = kf.eta_cone(state, KYIV_LAT, KYIV_LON)
        except Exception as e_kf:
            logger.debug(f"Kalman track fusion fallback: {e_kf}")

        drone_obj = {
            "id": track_id,
            "label": label,
            "category": category,
            "color": color,
            "threat_type": m.get("threat_type") or category,
            "lat": float(lat),
            "lng": float(lng),
            "heading": heading_val,
            "speed_kmh": speed_val,
            "confidence": int(m.get("confidence_0_100") or 0),
            "place": m.get("place") or "",
            "region": m.get("region") or m.get("oblast") or "",
            "text": m.get("text") or "",
            "time": m.get("date") or datetime.datetime.utcnow().isoformat() + "Z",
            "distance_to_kyiv_km": dist_kyiv,
            "distance_to_dnipro_km": dist_dnipro,
            "distance_to_zaporizhzhia_km": dist_zp,
            "is_kyiv_threat": "kyiv_city" in relevant_obs or "kyiv_oblast" in relevant_obs,
            "is_dnipro_threat": "dnipropetrovsk" in relevant_obs,
            "is_zaporizhzhia_threat": "zaporizhzhia" in relevant_obs,
            "relevant_oblasts": relevant_obs,
            "trail": trail,
            "waypoints": waypoints,
            "eta_cone": eta_cone_data,
        }
        drones.append(drone_obj)

    # Sort drones by distance to Kyiv (closest first)
    drones.sort(key=lambda d: d["distance_to_kyiv_km"])

    result = {
        "count": len(drones),
        "kyiv_threat_count": oblast_threat_counts.get("kyiv_city", 0),
        "dnipro_threat_count": oblast_threat_counts.get("dnipropetrovsk", 0),
        "zaporizhzhia_threat_count": oblast_threat_counts.get("zaporizhzhia", 0),
        "oblast_threat_counts": oblast_threat_counts,
        "ballistic_threat": ballistic,
        "drones": drones,
        "source": "Neptun (neptun.in.ua)",
        "status": "online",
        "updated": datetime.datetime.utcnow().isoformat() + "Z",
    }

    if r:
        try:
            r.setex(CACHE_KEY, CACHE_TTL, json.dumps(result))
        except Exception as e:
            logger.warning(f"Neptun radar cache set error: {e}")

    # Return filtered by oblast if requested
    if oblast and oblast != "all":
        direct_drones, inbound_drones = filter_drones_for_oblast(drones, oblast)
        return {
            **result,
            "drones": direct_drones,
            "inbound_drones": inbound_drones,
            "count": len(direct_drones),
            "direct_count": len(direct_drones),
            "inbound_count": len(inbound_drones),
            "total_threat_count": len(direct_drones) + len(inbound_drones)
        }

    return {
        **result,
        "inbound_drones": [],
        "direct_count": len(drones),
        "inbound_count": 0,
        "total_threat_count": len(drones)
    }
