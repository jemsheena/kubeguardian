"""Remediation logic — deletes broken pods and restarts owning Deployments."""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from kubernetes import client
from kubernetes.client.rest import ApiException

from controller import config
from controller.incident_log import log_incident
from controller.metrics import INCIDENTS_RESOLVED, POD_RESTARTS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Incident:
    namespace: str
    pod_name: str
    reason: str  # CrashLoopBackOff | Pending | Failed


class Healer:
    """Applies remediation actions with per-pod cooldown."""

    def __init__(self, api_client: client.ApiClient | None = None) -> None:
        self._core = client.CoreV1Api(api_client)
        self._apps = client.AppsV1Api(api_client)
        self._last_heal: dict[str, float] = {}

    def _cooldown_key(self, incident: Incident) -> str:
        deployment = self._find_owning_deployment(incident.namespace, incident.pod_name)
        owner = deployment or incident.pod_name
        return f"{incident.namespace}/{owner}:{incident.reason}"

    def _on_cooldown(self, incident: Incident, cooldown_key: str) -> bool:
        last = self._last_heal.get(cooldown_key)
        if last is None:
            return False
        elapsed = time.monotonic() - last
        if elapsed < config.HEAL_COOLDOWN_SECONDS:
            logger.info(
                "Skipping %s/%s — cooldown active (%.0fs remaining)",
                incident.namespace,
                incident.pod_name,
                config.HEAL_COOLDOWN_SECONDS - elapsed,
            )
            return True
        return False

    def _mark_healed(self, key: str) -> None:
        self._last_heal[key] = time.monotonic()

    def heal(self, incident: Incident) -> bool:
        """Remediate a detected incident. Returns True if an action was taken."""
        cooldown_key = self._cooldown_key(incident)
        if self._on_cooldown(incident, cooldown_key):
            return False

        if incident.reason == "CrashLoopBackOff":
            return self._delete_pod(incident, cooldown_key)
        if incident.reason in ("Pending", "Failed"):
            return self._restart_deployment(incident, cooldown_key)
        logger.warning("Unknown incident reason: %s", incident.reason)
        return False

    def _delete_pod(self, incident: Incident, cooldown_key: str) -> bool:
        action = "delete_pod"
        try:
            self._core.delete_namespaced_pod(
                name=incident.pod_name,
                namespace=incident.namespace,
                body=client.V1DeleteOptions(grace_period_seconds=0),
            )
            self._mark_healed(cooldown_key)
            POD_RESTARTS.labels(namespace=incident.namespace, action=action).inc()
            INCIDENTS_RESOLVED.labels(namespace=incident.namespace, reason=incident.reason).inc()
            log_incident(
                incident.namespace,
                incident.pod_name,
                incident.reason,
                action,
                resolved=True,
            )
            logger.info("Deleted pod %s/%s (CrashLoopBackOff)", incident.namespace, incident.pod_name)
            return True
        except ApiException as exc:
            if exc.status == 404:
                logger.info("Pod %s/%s already gone", incident.namespace, incident.pod_name)
                return False
            logger.error("Failed to delete pod %s/%s: %s", incident.namespace, incident.pod_name, exc)
            log_incident(incident.namespace, incident.pod_name, incident.reason, action, resolved=False)
            return False

    def _find_owning_deployment(self, namespace: str, pod_name: str) -> str | None:
        try:
            pod = self._core.read_namespaced_pod(name=pod_name, namespace=namespace)
        except ApiException:
            return None

        for owner in pod.metadata.owner_references or []:
            if owner.kind == "ReplicaSet":
                try:
                    rs = self._apps.read_namespaced_replica_set(
                        name=owner.name, namespace=namespace
                    )
                except ApiException:
                    continue
                for rs_owner in rs.metadata.owner_references or []:
                    if rs_owner.kind == "Deployment":
                        return rs_owner.name
            if owner.kind == "Deployment":
                return owner.name
        return None

    def _restart_deployment(self, incident: Incident, cooldown_key: str) -> bool:
        action = "rollout_restart"
        deployment = self._find_owning_deployment(incident.namespace, incident.pod_name)
        if not deployment:
            logger.warning(
                "No owning Deployment for %s/%s — falling back to pod delete",
                incident.namespace,
                incident.pod_name,
            )
            return self._delete_pod(incident, cooldown_key)

        restart_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        patch = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kubeguardian/restartedAt": restart_ts,
                        }
                    }
                }
            }
        }
        try:
            self._apps.patch_namespaced_deployment(
                name=deployment,
                namespace=incident.namespace,
                body=patch,
            )
            self._mark_healed(cooldown_key)
            POD_RESTARTS.labels(namespace=incident.namespace, action=action).inc()
            INCIDENTS_RESOLVED.labels(namespace=incident.namespace, reason=incident.reason).inc()
            log_incident(
                incident.namespace,
                incident.pod_name,
                incident.reason,
                f"{action}:{deployment}",
                resolved=True,
            )
            logger.info(
                "Rollout restart on Deployment %s/%s for pod %s",
                incident.namespace,
                deployment,
                incident.pod_name,
            )
            return True
        except ApiException as exc:
            logger.error(
                "Failed to restart Deployment %s/%s: %s",
                incident.namespace,
                deployment,
                exc,
            )
            log_incident(incident.namespace, incident.pod_name, incident.reason, action, resolved=False)
            return False
