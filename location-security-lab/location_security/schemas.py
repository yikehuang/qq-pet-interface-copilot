from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class GeoPoint(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timestamp_ms: int = Field(ge=0)
    accuracy_m: float | None = Field(default=None, ge=0)


class NetworkEvidence(BaseModel):
    server_ip_geo: GeoPoint | None = None
    wifi_consistent_with_claimed_area: bool | None = None
    cell_consistent_with_claimed_area: bool | None = None


class DeviceEvidence(BaseModel):
    mock_location: bool = False
    emulator_detected: bool = False
    root_detected: bool = False
    hook_risk_detected: bool = False
    meets_basic_integrity: bool | None = None
    meets_device_integrity: bool | None = None
    meets_strong_integrity: bool | None = None


class SensorEvidence(BaseModel):
    stationary: bool | None = None
    motion_score: float | None = Field(default=None, ge=0)


class EvaluationRequest(BaseModel):
    current: GeoPoint
    previous: GeoPoint | None = None
    network: NetworkEvidence = Field(default_factory=NetworkEvidence)
    device: DeviceEvidence = Field(default_factory=DeviceEvidence)
    sensors: SensorEvidence = Field(default_factory=SensorEvidence)


class Finding(BaseModel):
    code: str
    score: int = Field(ge=0)
    detail: str


class EvaluationResult(BaseModel):
    risk_score: int = Field(ge=0, le=100)
    level: Literal["low", "medium", "high", "critical"]
    findings: list[Finding]
    metrics: dict[str, float | int | str | bool | None]
