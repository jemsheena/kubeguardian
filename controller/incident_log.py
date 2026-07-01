"""Append-only JSON-lines incident log (PostgreSQL placeholder for later phases)."""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from controller.config import INCIDENT_LOG_PATH

logger = logging.getLogger(__name__)


def _ensure_log_dir() -> None:
    log_dir = Path(INCIDENT_LOG_PATH).parent
    log_dir.mkdir(parents=True, exist_ok=True)


def log_incident(
    namespace: str,
    pod_name: str,
    reason: str,
    action: str,
    *,
    resolved: bool = False,
) -> None:
    """Append one incident record as a JSON line."""
    _ensure_log_dir()
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "namespace": namespace,
        "pod": pod_name,
        "reason": reason,
        "action": action,
        "resolved": resolved,
    }
    with open(INCIDENT_LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + os.linesep)
    logger.info("Incident logged: %s/%s reason=%s action=%s", namespace, pod_name, reason, action)
