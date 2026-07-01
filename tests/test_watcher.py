"""Tests for pod failure detection in the watcher."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from kubernetes import client

from controller import config as app_config
from controller.watcher import _detect_failure, _pod_age_seconds
from tests.conftest import make_pod


class TestPodAgeSeconds:
    def test_returns_zero_without_creation_timestamp(self) -> None:
        pod = client.V1Pod(metadata=client.V1ObjectMeta(name="x", namespace="default"))
        assert _pod_age_seconds(pod) == 0.0

    def test_computes_age_from_creation_timestamp(self) -> None:
        created = datetime(2026, 1, 1, tzinfo=timezone.utc)
        pod = client.V1Pod(
            metadata=client.V1ObjectMeta(
                name="x",
                namespace="default",
                creation_timestamp=created,
            )
        )
        with patch("controller.watcher.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 1, 1, 0, 2, 0, tzinfo=timezone.utc)
            assert _pod_age_seconds(pod) == 120.0


class TestDetectFailure:
    def test_failed_phase(self) -> None:
        pod = make_pod(phase="Failed")
        assert _detect_failure(pod) == "Failed"

    def test_pending_below_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(app_config, "PENDING_THRESHOLD_SECONDS", 120)
        pod = make_pod(phase="Pending", age_seconds=60)
        assert _detect_failure(pod) is None

    def test_pending_at_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(app_config, "PENDING_THRESHOLD_SECONDS", 120)
        pod = make_pod(phase="Pending", age_seconds=120)
        assert _detect_failure(pod) == "Pending"

    def test_crash_loop_backoff(self) -> None:
        pod = make_pod(phase="Running", waiting_reason="CrashLoopBackOff")
        assert _detect_failure(pod) == "CrashLoopBackOff"

    def test_terminated_error_treated_as_crashloop(self) -> None:
        pod = make_pod(phase="Running", terminated_reason="Error")
        assert _detect_failure(pod) == "CrashLoopBackOff"

    def test_oom_killed_treated_as_crashloop(self) -> None:
        pod = make_pod(phase="Running", terminated_reason="OOMKilled")
        assert _detect_failure(pod) == "CrashLoopBackOff"

    def test_healthy_running_pod(self) -> None:
        pod = make_pod(phase="Running")
        assert _detect_failure(pod) is None

    def test_succeeded_pod_ignored(self) -> None:
        pod = make_pod(phase="Succeeded")
        assert _detect_failure(pod) is None
