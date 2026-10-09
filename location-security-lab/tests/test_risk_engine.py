from location_security.risk_engine import evaluate_risk
from location_security.schemas import EvaluationRequest


def test_clean_scenario_is_low_risk() -> None:
    req = EvaluationRequest.model_validate(
        {
            "previous": {
                "latitude": 51.45450,
                "longitude": -2.58790,
                "timestamp_ms": 1_000_000,
            },
            "current": {
                "latitude": 51.45472,
                "longitude": -2.58770,
                "timestamp_ms": 1_030_000,
            },
            "device": {
                "meets_basic_integrity": True,
                "meets_device_integrity": True,
            },
            "sensors": {"stationary": False},
        }
    )

    result = evaluate_risk(req)
    assert result.level == "low"
    assert result.risk_score == 0


def test_mock_emulator_integrity_failure_is_high_risk() -> None:
    req = EvaluationRequest.model_validate(
        {
            "current": {
                "latitude": 31.230416,
                "longitude": 121.473701,
                "timestamp_ms": 2_000_000,
            },
            "device": {
                "mock_location": True,
                "emulator_detected": True,
                "meets_device_integrity": False,
            },
        }
    )

    result = evaluate_risk(req)
    assert result.level == "high"
    assert result.risk_score == 75
    assert {f.code for f in result.findings} >= {
        "mock_location",
        "emulator",
        "device_integrity_failed",
    }


def test_teleport_and_stationary_sensor_conflict() -> None:
    req = EvaluationRequest.model_validate(
        {
            "previous": {
                "latitude": 51.4545,
                "longitude": -2.5879,
                "timestamp_ms": 3_000_000,
            },
            "current": {
                "latitude": 51.5074,
                "longitude": -0.1278,
                "timestamp_ms": 3_005_000,
            },
            "sensors": {"stationary": True},
        }
    )

    result = evaluate_risk(req)
    codes = {f.code for f in result.findings}
    assert "teleport_extreme" in codes
    assert "sensor_location_conflict" in codes
    assert result.risk_score == 60
    assert result.level == "high"
