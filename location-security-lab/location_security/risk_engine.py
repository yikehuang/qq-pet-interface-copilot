from __future__ import annotations

from .schemas import EvaluationRequest, EvaluationResult, Finding
from .trajectory import haversine_m, speed_mps


def _level(score: int) -> str:
    if score >= 80:
        return "critical"
    if score >= 60:
        return "high"
    if score >= 30:
        return "medium"
    return "low"


def evaluate_risk(req: EvaluationRequest) -> EvaluationResult:
    findings: list[Finding] = []
    metrics: dict[str, float | int | str | bool | None] = {}

    def add(code: str, score: int, detail: str) -> None:
        findings.append(Finding(code=code, score=score, detail=detail))

    d = req.device

    if d.mock_location:
        add("mock_location", 25, "客户端报告当前位置来自 Mock Location。")

    if d.emulator_detected:
        add("emulator", 20, "运行环境具有模拟器特征。")

    if d.root_detected:
        add("root", 15, "设备存在 Root 风险信号。")

    if d.hook_risk_detected:
        add("hook_risk", 25, "检测到运行时 Hook/注入风险信号。")

    if d.meets_device_integrity is False:
        add("device_integrity_failed", 30, "设备未满足设备完整性要求。")
    elif d.meets_device_integrity is True:
        metrics["meets_device_integrity"] = True

    if d.meets_basic_integrity is False:
        add("basic_integrity_failed", 15, "设备未满足基础完整性要求。")

    if d.meets_strong_integrity is False:
        add("strong_integrity_failed", 5, "设备未满足强完整性要求；该信号仅作低权重辅助证据。")

    network = req.network

    if network.server_ip_geo is not None:
        ip_distance_m = haversine_m(req.current, network.server_ip_geo)
        ip_distance_km = ip_distance_m / 1000.0
        metrics["gps_ip_distance_km"] = round(ip_distance_km, 3)

        if ip_distance_km >= 1000:
            add("gps_ip_far", 15, f"GPS 与服务端观测 IP 地理位置相距约 {ip_distance_km:.0f} km。")
        elif ip_distance_km >= 300:
            add("gps_ip_mismatch", 10, f"GPS 与服务端观测 IP 地理位置相距约 {ip_distance_km:.0f} km。")
        elif ip_distance_km >= 100:
            add("gps_ip_soft_mismatch", 5, f"GPS 与 IP 地理位置存在约 {ip_distance_km:.0f} km 偏差。")

    if network.wifi_consistent_with_claimed_area is False:
        add("wifi_area_mismatch", 10, "Wi-Fi 环境与声称位置不一致。")

    if network.cell_consistent_with_claimed_area is False:
        add("cell_area_mismatch", 15, "蜂窝网络环境与声称位置不一致。")

    if req.previous is not None:
        distance_m = haversine_m(req.previous, req.current)
        speed = speed_mps(req.previous, req.current)
        metrics["trajectory_distance_m"] = round(distance_m, 3)
        metrics["trajectory_speed_mps"] = None if speed is None else round(speed, 3)

        if speed is None:
            add("invalid_time_delta", 10, "连续定位点时间戳无有效间隔。")
        elif speed >= 300:
            add("teleport_extreme", 35, f"轨迹推算速度约 {speed:.1f} m/s，属于极端异常。")
        elif speed >= 80:
            add("speed_very_high", 20, f"轨迹推算速度约 {speed:.1f} m/s，明显异常。")
        elif speed >= 45:
            add("speed_high", 10, f"轨迹推算速度约 {speed:.1f} m/s，需要进一步验证。")

        if req.sensors.stationary is True and speed is not None and speed >= 10:
            add(
                "sensor_location_conflict",
                25,
                "传感器显示设备静止，但定位轨迹表现为高速移动。",
            )

    score = min(100, sum(item.score for item in findings))
    findings.sort(key=lambda item: item.score, reverse=True)

    return EvaluationResult(
        risk_score=score,
        level=_level(score),
        findings=findings,
        metrics=metrics,
    )
