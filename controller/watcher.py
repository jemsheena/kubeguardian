"""Kubernetes API watcher — detects CrashLoopBackOff, Pending, and Failed pods."""

import logging
import queue
import threading
import time
from datetime import datetime, timezone

from kubernetes import client, config, watch
from kubernetes.client.rest import ApiException

from controller import config as app_config
from controller.healer import Incident
from controller.metrics import INCIDENTS_DETECTED

logger = logging.getLogger(__name__)


def load_kube_config() -> client.ApiClient:
    """Load in-cluster config when running inside a pod, else local kubeconfig."""
    import os

    if os.getenv("KUBERNETES_SERVICE_HOST"):
        config.load_incluster_config()
        logger.info("Loaded in-cluster Kubernetes config")
    else:
        config.load_kube_config()
        logger.info("Loaded local kubeconfig")
    return client.ApiClient()


def _pod_age_seconds(pod: client.V1Pod) -> float:
    created = pod.metadata.creation_timestamp
    if created is None:
        return 0.0
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - created).total_seconds()


def _detect_failure(pod: client.V1Pod) -> str | None:
    """Return failure reason if the pod should be healed, else None."""
    phase = pod.status.phase

    if phase == "Failed":
        return "Failed"

    if phase == "Pending":
        age = _pod_age_seconds(pod)
        if age >= app_config.PENDING_THRESHOLD_SECONDS:
            return "Pending"
        return None

    if phase == "Running":
        for cs in pod.status.container_statuses or []:
            waiting = cs.state.waiting
            if waiting and waiting.reason == "CrashLoopBackOff":
                return "CrashLoopBackOff"
            terminated = cs.state.terminated
            if terminated and terminated.reason in ("Error", "OOMKilled"):
                return "CrashLoopBackOff"

    return None


class PodWatcher:
    """Watches pods and enqueues incidents for the healer."""

    def __init__(
        self,
        incident_queue: queue.Queue[Incident],
        api_client: client.ApiClient | None = None,
    ) -> None:
        self._queue = incident_queue
        self._core = client.CoreV1Api(api_client)
        self._seen: set[str] = set()
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def _emit(self, incident: Incident) -> None:
        key = f"{incident.namespace}/{incident.pod_name}:{incident.reason}"
        if key in self._seen:
            return
        self._seen.add(key)
        INCIDENTS_DETECTED.labels(namespace=incident.namespace, reason=incident.reason).inc()
        logger.warning(
            "Incident detected: %s/%s — %s",
            incident.namespace,
            incident.pod_name,
            incident.reason,
        )
        self._queue.put(incident)

    def _handle_pod(self, pod: client.V1Pod) -> None:
        if not pod.metadata or not pod.metadata.name or not pod.metadata.namespace:
            return
        reason = _detect_failure(pod)
        if reason:
            self._emit(
                Incident(
                    namespace=pod.metadata.namespace,
                    pod_name=pod.metadata.name,
                    reason=reason,
                )
            )

    def _watch_namespace(self, namespace: str | None) -> None:
        w = watch.Watch()
        label = namespace or "all namespaces"
        while not self._stop.is_set():
            try:
                if namespace:
                    stream = w.stream(
                        self._core.list_namespaced_pod,
                        namespace=namespace,
                        timeout_seconds=app_config.POLL_INTERVAL,
                    )
                else:
                    stream = w.stream(
                        self._core.list_pod_for_all_namespaces,
                        timeout_seconds=app_config.POLL_INTERVAL,
                    )
                for event in stream:
                    if self._stop.is_set():
                        break
                    pod = event["object"]
                    if event["type"] in ("ADDED", "MODIFIED"):
                        self._handle_pod(pod)
            except ApiException as exc:
                logger.error("Watch error in %s: %s", label, exc)
                time.sleep(app_config.POLL_INTERVAL)
            except Exception as exc:
                logger.error("Unexpected watch error in %s: %s", label, exc)
                time.sleep(app_config.POLL_INTERVAL)
            finally:
                w.stop()
                w = watch.Watch()

    def run(self) -> None:
        """Block and watch pods until stop() is called."""
        namespaces = app_config.WATCH_NAMESPACES
        if not namespaces:
            self._watch_namespace(None)
        else:
            threads = [
                threading.Thread(
                    target=self._watch_namespace,
                    args=(ns,),
                    name=f"watcher-{ns}",
                    daemon=True,
                )
                for ns in namespaces
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
