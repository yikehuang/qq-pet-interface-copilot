from __future__ import annotations

import json
from pathlib import Path

BASE_TS = 1_800_000_000_000


def point(lat: float, lon: float, offset_ms: int) -> dict:
    return {
        "latitude": lat,
        "longitude": lon,
        "timestamp_ms": BASE_TS + offset_ms,
        "accuracy_m": 8.0,
    }


SCENARIOS = {
    "normal_walk": {
        "previous": point(51.45450, -2.58790, 0),
        "current": point(51.45472, -2.58770, 30_000),
        "network": {
            "server_ip_geo": point(51.45450, -2.58790, 30_000),
            "wifi_consistent_with_claimed_area": True,
            "cell_consistent_with_claimed_area": True,
        },
        "device": {
            "meets_basic_integrity": True,
            "meets_device_integrity": True,
        },
        "sensors": {"stationary": False, "motion_score": 0.7},
    },
    "mock_emulator": {
        "current": point(31.230416, 121.473701, 30_000),
        "network": {
            "server_ip_geo": point(51.5074, -0.1278, 30_000),
            "wifi_consistent_with_claimed_area": False,
        },
        "device": {
            "mock_location": True,
            "emulator_detected": True,
            "root_detected": True,
            "meets_device_integrity": False,
        },
        "sensors": {"stationary": True, "motion_score": 0.0},
    },
    "teleport": {
        "previous": point(51.45450, -2.58790, 0),
        "current": point(51.50740, -0.12780, 5_000),
        "device": {
            "meets_basic_integrity": True,
            "meets_device_integrity": True,
        },
        "sensors": {"stationary": True, "motion_score": 0.0},
    },
}


def main() -> None:
    out = Path(__file__).with_name("generated")
    out.mkdir(exist_ok=True)

    for name, body in SCENARIOS.items():
        path = out / f"{name}.json"
        path.write_text(
            json.dumps(body, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(path)


if __name__ == "__main__":
    main()
