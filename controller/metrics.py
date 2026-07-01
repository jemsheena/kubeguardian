"""Prometheus metrics exporter for KubeGuardian."""

from prometheus_client import Counter, start_http_server

from controller.config import METRICS_PORT

INCIDENTS_DETECTED = Counter(
    "incidents_detected_total",
    "Total number of pod failure incidents detected",
    ["namespace", "reason"],
)

INCIDENTS_RESOLVED = Counter(
    "incidents_resolved_total",
    "Total number of incidents successfully remediated",
    ["namespace", "reason"],
)

POD_RESTARTS = Counter(
    "pod_restarts_total",
    "Total number of pod restart/remediation actions taken",
    ["namespace", "action"],
)


def start_metrics_server(port: int | None = None) -> None:
    """Start the Prometheus /metrics HTTP endpoint in a background thread."""
    start_http_server(port or METRICS_PORT)
