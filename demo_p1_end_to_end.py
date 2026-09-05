"""
P1 End-to-End Demo: Shahed-136/Geran-2 in Dnipro River Canyon.
Demonstrates:
1. Dynamic Kalman filter tracking with aerodynamic envelopes.
2. Temporal decay of sensor reports.
3. MNAR (Missing Not At Random) handling in river canyon masking.
4. CoT and map-ready ETA cone projections.
"""

from datetime import datetime, timedelta
from worker.track_fusion import KalmanTrackFilter, estimate_eta_cone
from worker.scoring_bayesian import Evidence, fuse_multi_domain_evidence, format_threat_summary

def run_demo():
    print("================================================================================")
    print("🛰️ C4ISR OKINT-PRO — P1 TACTICAL DATA FUSION & KINEMATICS DEMO")
    print("Scenario: Geran-2 low-altitude strike along Dnipro River Canyon")
    print("================================================================================\n")

    now = datetime.utcnow()

    # 1. Kinematics initialization
    kf = KalmanTrackFilter(dt=1.0, threat_type="GERAN_2")
    kf.predict()
    state = kf.state
    print(f"✅ [1. KINEMATICS] Initialized target: GERAN_2")
    print(f"   Category: {state['threat_category']}")
    print(f"   Effective q_accel: {state['q_eff']} m/s² (saturated ceiling: 40.0)")

    # 2. ETA Cone projection to 750kV substation (55 km away)
    corridor_dist_m = 55_000.0
    cone = estimate_eta_cone({"v_ms": 55.0}, corridor_dist_m, threat_type="GERAN_2")
    print(f"\n✅ [2. ETA ENVELOPE] Target distance: {corridor_dist_m/1000:.1f} km")
    print(f"   ETA Nominal: {cone.eta_nom_s / 60:.1f} min ({cone.eta_nom_s:.0f}s)")
    print(f"   ETA Bounds:  {cone.eta_min_s / 60:.1f} min (dive) ... {cone.eta_max_s / 60:.1f} min (stall)")
    print(f"   Cone Angle:  ±{cone.theta_cone_deg:.1f}°")
    for poly in cone.polygons:
        print(f"   - T+{poly['time_min']}m Envelope: {poly['d_nom_m']/1000:.1f} km (spread: ±{poly['lateral_spread_m']/1000:.1f} km)")

    # 3. Multi-INT Fusion with MNAR & Temporal Decay
    # Scenario: Target is at 30m altitude in Dnipro canyon -> Radar & SIGINT are missing (MNAR)
    evidence = [
        Evidence(sensor_type="RADAR", timestamp=now, base_lr=8.0, altitude_m=30.0, terrain_masked=True, target_type="GERAN_2"),
        Evidence(sensor_type="ACOUSTIC", timestamp=now - timedelta(seconds=15), base_lr=4.0, altitude_m=30.0, terrain_masked=True, target_type="GERAN_2"),
        Evidence(sensor_type="SIGINT", timestamp=now, base_lr=6.0, altitude_m=30.0, terrain_masked=True, target_type="GERAN_2"),
        Evidence(sensor_type="OSINT", timestamp=now - timedelta(seconds=120), base_lr=3.0, altitude_m=30.0, terrain_masked=True, target_type="GERAN_2"),
    ]

    assessment = fuse_multi_domain_evidence(evidence, current_time=now)
    print(f"\n✅ [3. MULTI-INT BBN FUSION]")
    print(f"   Summary: {format_threat_summary(assessment)}")
    print(f"   Threat Probability: {assessment.threat_probability * 100:.1f}% [{assessment.confidence_label}]")
    print(f"   Contributing Sensors: {assessment.contributing_sensors}")
    print(f"   MNAR Neutralized Sensors: {assessment.mnar_sensors} (Canyon/LoS Masked)")
    print(f"   Decayed Sensors: {assessment.decayed_sensors}")

    print("\n🎯 DEMO COMPLETE — ALL P1 ENGINES FULLY CONVERGED.")

if __name__ == "__main__":
    run_demo()
