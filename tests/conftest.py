"""Shared fixtures for KubeGuardian unit tests."""

from datetime import datetime, timedelta, timezone

import pytest
from kubernetes import client


@pytest.fixture
def namespace() -> str:
    return "default"


def make_pod(
    name: str = "test-pod",
    namespace: str = "default",
    *,
    phase: str = "Running",
    age_seconds: float | None = None,
    waiting_reason: str | None = None,
    terminated_reason: str | None = None,
    owner_references: list[client.V1OwnerReference] | None = None,
) -> client.V1Pod:
    metadata = client.V1ObjectMeta(
        name=name,
        namespace=namespace,
        owner_references=owner_references,
    )
    if age_seconds is not None:
        created = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
        metadata.creation_timestamp = created

    status = client.V1PodStatus(phase=phase)

    if waiting_reason or terminated_reason:
        container_status = client.V1ContainerStatus(
            name="app",
            image="busybox:latest",
            image_id="docker://sha256:test",
            ready=False,
            restart_count=0,
        )
        if waiting_reason:
            container_status.state = client.V1ContainerState(
                waiting=client.V1ContainerStateWaiting(reason=waiting_reason)
            )
        elif terminated_reason:
            container_status.state = client.V1ContainerState(
                terminated=client.V1ContainerStateTerminated(
                    reason=terminated_reason,
                    exit_code=137 if terminated_reason == "OOMKilled" else 1,
                )
            )
        status.container_statuses = [container_status]

    return client.V1Pod(metadata=metadata, status=status)


def make_owner_reference(kind: str, name: str) -> client.V1OwnerReference:
    return client.V1OwnerReference(
        api_version="apps/v1",
        kind=kind,
        name=name,
        uid="test-uid",
        controller=True,
    )
