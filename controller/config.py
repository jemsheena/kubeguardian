"""Configuration constants for the KubeGuardian controller."""

import os

# How often the watcher re-lists pods when the watch stream reconnects (seconds).
POLL_INTERVAL: int = int(os.getenv("POLL_INTERVAL", "5"))

# Comma-separated namespace list. Empty string watches all namespaces.
_namespaces_raw = os.getenv("WATCH_NAMESPACES", "")
WATCH_NAMESPACES: list[str] = (
    [ns.strip() for ns in _namespaces_raw.split(",") if ns.strip()]
    if _namespaces_raw
    else []
)

# Pods stuck in Pending longer than this are treated as incidents (seconds).
PENDING_THRESHOLD_SECONDS: int = int(os.getenv("PENDING_THRESHOLD_SECONDS", "120"))

# Minimum time between healing actions on the same pod (seconds).
HEAL_COOLDOWN_SECONDS: int = int(os.getenv("HEAL_COOLDOWN_SECONDS", "300"))

# JSON-lines incident log path.
INCIDENT_LOG_PATH: str = os.getenv("INCIDENT_LOG_PATH", "/var/log/kubeguardian/incidents.jsonl")

# Prometheus /metrics port.
METRICS_PORT: int = int(os.getenv("METRICS_PORT", "8000"))

# Log level.
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
