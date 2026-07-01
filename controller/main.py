"""Entry point — starts watcher, metrics server, and healer loop."""

import logging
import queue
import signal
import sys
import threading

from controller import config
from controller.healer import Healer, Incident
from controller.metrics import start_metrics_server
from controller.watcher import PodWatcher, load_kube_config

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _healer_loop(healer: Healer, incident_queue: queue.Queue[Incident], stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            incident = incident_queue.get(timeout=1)
        except queue.Empty:
            continue
        try:
            healer.heal(incident)
        except Exception:
            logger.exception("Healer error for %s/%s", incident.namespace, incident.pod_name)
        finally:
            incident_queue.task_done()


def main() -> None:
    logger.info("Starting KubeGuardian controller")
    stop = threading.Event()
    incident_queue: queue.Queue[Incident] = queue.Queue()

    api_client = load_kube_config()
    healer = Healer(api_client)
    watcher = PodWatcher(incident_queue, api_client)

    start_metrics_server()
    logger.info("Metrics server listening on :%d/metrics", config.METRICS_PORT)

    healer_thread = threading.Thread(
        target=_healer_loop,
        args=(healer, incident_queue, stop),
        name="healer",
        daemon=True,
    )
    watcher_thread = threading.Thread(target=watcher.run, name="watcher", daemon=True)

    def _shutdown(signum: int, _frame: object) -> None:
        logger.info("Received signal %s — shutting down", signum)
        stop.set()
        watcher.stop()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    healer_thread.start()
    watcher_thread.start()
    logger.info("Watcher and healer loops running")

    try:
        watcher_thread.join()
    except KeyboardInterrupt:
        _shutdown(signal.SIGINT, None)

    stop.set()
    watcher.stop()
    logger.info("KubeGuardian stopped")
    sys.exit(0)


if __name__ == "__main__":
    main()
