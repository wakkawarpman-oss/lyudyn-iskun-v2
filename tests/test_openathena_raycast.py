from worker.osint.drone_raycast import calculate_raycast_target, parse_drone_xmp_metadata


def test_nadir_raycast():
    res = calculate_raycast_target(
        drone_lat=50.4500,
        drone_lon=30.5200,
        drone_alt_m=300.0,
        gimbal_pitch_deg=-90.0,
        gimbal_yaw_deg=0.0,
        ground_alt_m=100.0
    )
    assert res.target_lat == 50.4500
    assert res.target_lon == 30.5200
    assert res.ground_range_m < 0.1
    assert res.slant_range_m == 200.0
    assert res.confidence == "HIGH"


def test_angled_raycast_east():
    # 45 degrees down looking East (yaw=90)
    res = calculate_raycast_target(
        drone_lat=50.4500,
        drone_lon=30.5200,
        drone_alt_m=220.0,
        gimbal_pitch_deg=-45.0,
        gimbal_yaw_deg=90.0,
        ground_alt_m=120.0
    )
    assert res.target_lat == 50.4500
    assert res.target_lon > 30.5200
    assert abs(res.ground_range_m - 100.0) < 1.0
    assert abs(res.slant_range_m - 141.4) < 1.0


def test_pixel_offset_raycast():
    # Target in right portion of frame (px_norm = 0.5)
    res_center = calculate_raycast_target(
        drone_lat=50.4500,
        drone_lon=30.5200,
        drone_alt_m=220.0,
        gimbal_pitch_deg=-45.0,
        gimbal_yaw_deg=0.0,
        px_norm=0.0,
        ground_alt_m=120.0
    )
    res_right = calculate_raycast_target(
        drone_lat=50.4500,
        drone_lon=30.5200,
        drone_alt_m=220.0,
        gimbal_pitch_deg=-45.0,
        gimbal_yaw_deg=0.0,
        px_norm=0.5,
        ground_alt_m=120.0
    )
    # Right of frame when looking North means target is further East
    assert res_right.target_lon > res_center.target_lon


def test_unreliable_horizon_pitch():
    # Looking above or at horizon
    res = calculate_raycast_target(
        drone_lat=50.4500,
        drone_lon=30.5200,
        drone_alt_m=200.0,
        gimbal_pitch_deg=5.0,
        gimbal_yaw_deg=0.0,
        ground_alt_m=100.0
    )
    assert res.confidence == "UNRELIABLE"


def test_parse_drone_xmp_metadata():
    mock_jpeg_header = (
        b"\xff\xd8\xff\xe1\x10\x00http://ns.adobe.com/xap/1.0/\x00"
        b"<x:xmpmeta><rdf:RDF><rdf:Description "
        b'drone-dji:GimbalPitchDegree="-45.5" '
        b'drone-dji:GimbalYawDegree="124.2" '
        b'drone-dji:AbsoluteAltitude="215.4" '
        b"/></rdf:RDF></x:xmpmeta>"
    )
    meta = parse_drone_xmp_metadata(mock_jpeg_header)
    assert meta.get("gimbal_pitch") == -45.5
    assert meta.get("gimbal_yaw") == 124.2
    assert meta.get("abs_alt") == 215.4
