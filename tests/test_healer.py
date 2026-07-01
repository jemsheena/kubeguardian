"""Tests for remediation logic in the healer."""

import time
from unittest.mock import ANY, MagicMock, patch

import pytest
from kubernetes import client
from kubernetes.client.rest import ApiException

from controller import config
from controller.healer import Healer, Incident
from tests.conftest import make_owner_reference, make_pod


@pytest.fixture
def mock_api_client() -> MagicMock:
    return MagicMock()


@pytest.fixture
def healer(mock_api_client: MagicMock) -> Healer:
    with patch("controller.healer.client.CoreV1Api") as core_cls, patch(
        "controller.healer.client.AppsV1Api"
    ) as apps_cls:
        core = MagicMock()
        apps = MagicMock()
        core_cls.return_value = core
        apps_cls.return_value = apps
        instance = Healer(mock_api_client)
        instance._core = core
        instance._apps = apps
        yield instance


class TestHealRouting:
    def test_crashloop_deletes_pod(self, healer: Healer) -> None:
        incident = Incident("default", "bad-pod", "CrashLoopBackOff")
        healer._core.delete_namespaced_pod.return_value = None

        with patch.object(healer, "_cooldown_key", return_value="default/bad-pod:CrashLoopBackOff"), patch(
            "controller.healer.log_incident"
        ):
            assert healer.heal(incident) is True

        healer._core.delete_namespaced_pod.assert_called_once()

    def test_pending_restarts_deployment(self, healer: Healer) -> None:
        incident = Incident("default", "pending-pod", "Pending")
        healer._find_owning_deployment = MagicMock(return_value="web")
        healer._apps.patch_namespaced_deployment.return_value = None

        with patch.object(healer, "_cooldown_key", return_value="default/web:Pending"), patch(
            "controller.healer.log_incident"
        ):
            assert healer.heal(incident) is True

        healer._apps.patch_namespaced_deployment.assert_called_once_with(
            name="web",
            namespace="default",
            body=ANY,
        )

    def test_unknown_reason_returns_false(self, healer: Healer) -> None:
        incident = Incident("default", "pod", "Unknown")
        with patch.object(healer, "_cooldown_key", return_value="default/pod:Unknown"):
            assert healer.heal(incident) is False


class TestCooldown:
    def test_skips_heal_during_cooldown(
        self, healer: Healer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(config, "HEAL_COOLDOWN_SECONDS", 300)
        incident = Incident("default", "pod", "CrashLoopBackOff")
        healer._last_heal["default/pod:CrashLoopBackOff"] = time.monotonic()

        assert healer.heal(incident) is False
        healer._core.delete_namespaced_pod.assert_not_called()


class TestDeletePod:
    def test_delete_success(self, healer: Healer) -> None:
        incident = Incident("default", "bad-pod", "CrashLoopBackOff")
        healer._core.delete_namespaced_pod.return_value = None

        with patch("controller.healer.log_incident") as log_mock:
            assert healer._delete_pod(incident, "key") is True

        log_mock.assert_called_once_with(
            "default", "bad-pod", "CrashLoopBackOff", "delete_pod", resolved=True
        )

    def test_delete_not_found_is_noop(self, healer: Healer) -> None:
        incident = Incident("default", "gone-pod", "CrashLoopBackOff")
        healer._core.delete_namespaced_pod.side_effect = ApiException(status=404)

        assert healer._delete_pod(incident, "key") is False


class TestRestartDeployment:
    def test_falls_back_to_delete_without_owner(self, healer: Healer) -> None:
        incident = Incident("default", "orphan-pod", "Failed")
        healer._find_owning_deployment = MagicMock(return_value=None)
        healer._core.delete_namespaced_pod.return_value = None

        with patch("controller.healer.log_incident"):
            assert healer._restart_deployment(incident, "key") is True

        healer._core.delete_namespaced_pod.assert_called_once()

    def test_patches_deployment_template(self, healer: Healer) -> None:
        incident = Incident("default", "pending-pod", "Pending")
        healer._find_owning_deployment = MagicMock(return_value="api")
        healer._apps.patch_namespaced_deployment.return_value = None

        with patch("controller.healer.log_incident") as log_mock:
            assert healer._restart_deployment(incident, "key") is True

        _, kwargs = healer._apps.patch_namespaced_deployment.call_args
        assert kwargs["name"] == "api"
        assert "kubeguardian/restartedAt" in kwargs["body"]["spec"]["template"]["metadata"]["annotations"]
        log_mock.assert_called_once()


class TestFindOwningDeployment:
    def test_direct_deployment_owner(self, healer: Healer) -> None:
        pod = make_pod(
            owner_references=[make_owner_reference("Deployment", "direct")]
        )
        healer._core.read_namespaced_pod.return_value = pod

        assert healer._find_owning_deployment("default", "pod") == "direct"

    def test_replicaset_to_deployment_chain(self, healer: Healer) -> None:
        pod = make_pod(
            owner_references=[make_owner_reference("ReplicaSet", "rs-abc")]
        )
        rs = client.V1ReplicaSet(
            metadata=client.V1ObjectMeta(
                owner_references=[make_owner_reference("Deployment", "via-rs")]
            )
        )
        healer._core.read_namespaced_pod.return_value = pod
        healer._apps.read_namespaced_replica_set.return_value = rs

        assert healer._find_owning_deployment("default", "pod") == "via-rs"
