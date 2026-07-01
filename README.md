# KubeGuardian

KubeGuardian is a lightweight Kubernetes pod health watcher and auto-healer for local kind clusters. It detects failing pods, remediates them automatically, exports Prometheus metrics, and logs incidents to a JSON-lines file.

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> Scope: this build targets a local kind cluster only — no cloud IAM, ingress controllers, or multi-cluster federation.

## Table of contents

- [Features](#features)
- [Demo](#demo)
- [Architecture](#architecture)
- [How it works](#how-it-works)
- [Project layout](#project-layout)
- [Getting started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Quick start](#quick-start)
    - [Option A](#option-a--on-the-host-recommended-for-kind)
    - [Option B](#option-b--via-docker-compose)
    - [Option C](#option-c--in-cluster-rbac-included)
- [Configuration](#configuration)
- [Metrics and observability](#metrics-and-observability)
- [Roadmap](#roadmap)
- [Development](#development)
- [Contributing](#contributing)
- [License](#license)

## Features

- Watch pods in a local kind cluster and detect CrashLoopBackOff, Pending, and Failed states.
- Heal crash-looping workloads by deleting pods and restarting rollout-managed workloads via Deployment patching.
- Expose Prometheus metrics for detected incidents, resolved incidents, and healing actions.
- Persist incidents as JSON-lines for local demos and future database-backed storage.
- Run alongside Prometheus and Grafana for live observability.

## Demo

These screenshots show real data captured from a running KubeGuardian demo with the controller, Prometheus, and Grafana all active.

The images demonstrate the project goal:
- detecting pod failures in a local kind cluster
- healing crashlooping workloads automatically
- exposing Prometheus metrics for incidents and actions
- logging incidents to a JSON-lines file
- showing live pod state from Kubernetes

| Grafana dashboard | Prometheus query |
|---|---|
| ![Grafana dashboard](docs/screenshots/Screenshot%202026-07-01%20221905.png) | ![Prometheus query](docs/screenshots/Screenshot%202026-07-01%20221915.png) |

| Metrics endpoint output | Pod state |
|---|---|
| ![Metrics endpoint output](docs/screenshots/Screenshot%202026-07-01%20221927.png) | ![Pod state](docs/screenshots/Screenshot%202026-07-01%20222300.png) |

## Architecture

```text
┌─────────────────────────────────────────────────────────────────┐
│                        kind cluster                              │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐ │
│  │ crashloop    │   │ healthy-demo │   │ other workloads      │ │
│  │ Deployment   │   │ Deployment   │   │                      │ │
│  └──────┬───────┘   └──────────────┘   └──────────────────────┘ │
└─────────┼───────────────────────────────────────────────────────┘
          │ Kubernetes API (watch)
          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    KubeGuardian Controller                       │
│  ┌──────────┐    ┌─────────────────┐    ┌────────────┐   ┌───────────┐ │
│  │ watcher  │───▶│      healer     │───▶│ incident   │   │ metrics   │ │
│  │ (watch)  │    │ patch annotation│    │ log (jsonl)│   │ :8000     │ │
│  └──────────┘    │  / delete pod   │    └────────────┘   └─────┬─────┘ │
│                  └─────────────────┘                                  │
└──────────────────────────────────────────────────────────┼──────┘
                                                           │ scrape
                                                           ▼
                                              ┌────────────────────┐
                                              │    Prometheus      │
                                              └─────────┬──────────┘
                                                        │
                                                        ▼
                                              ┌────────────────────┐
                                              │     Grafana        │
                                              │   (dashboard)      │
                                              └────────────────────┘
```

## How it works

### Detection and remediation

| Failure state | Detection rule | Action |
|---|---|---|
| CrashLoopBackOff | Container `waiting.reason` | Delete pod (controller recreates) |
| Pending | Phase Pending longer than threshold | Rollout restart owning Deployment |
| Failed | Phase `Failed` | Rollout restart owning Deployment |

For Pending and Failed rollout restarts, the healer resolves the owning Deployment by walking `ownerReferences` from pod → ReplicaSet → Deployment (or pod → Deployment when owned directly).

Default Pending threshold is 120 seconds (`PENDING_THRESHOLD_SECONDS`). The Compose stack overrides this to 60 seconds for faster local demos.

A per-workload cooldown prevents heal loops. The default is 300 seconds (`HEAL_COOLDOWN_SECONDS`), and the Compose stack sets it to 120 seconds.

## Project layout

```text
kubeguardian/
├── controller/           # Python controller
├── deploy/               # ServiceAccount, RBAC, in-cluster Deployment
├── docs/screenshots/     # README demo screenshots
├── tests/                # pytest unit tests
├── test-workloads/       # Demo Deployments for kind
├── monitoring/           # Prometheus + Grafana config
├── docker-compose.yml    # Controller + Prometheus + Grafana
├── Dockerfile
├── requirements.txt
└── requirements-dev.txt
```

## Getting started

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- [kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installation)
- [kubectl](https://kubernetes.io/docs/tasks/tools/)
- Python 3.11+ (for running the controller directly on the host)

### Quick start

#### 1. Create a local kind cluster

```bash
kind create cluster --name kubeguardian
kubectl cluster-info --context kind-kubeguardian
```

#### 2. Deploy test workloads

```bash
kubectl apply -f test-workloads/healthy-pod.yaml
kubectl apply -f test-workloads/crashloop-pod.yaml
kubectl get pods -w
```

Within a minute or two the crashloop pod should enter `CrashLoopBackOff`. The healthy pod should stay `Running`.

#### 3. Run the controller

##### Option A — on the host (recommended for kind)

The controller reads your local kubeconfig and talks to kind directly:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m controller.main
```

For incident logs on the host, set a writable path (the default `/var/log/...` path is intended for containers):

```powershell
# Windows PowerShell
$env:INCIDENT_LOG_PATH = ".\incidents.jsonl"
python -m controller.main
```

##### Option B — via Docker Compose

```bash
docker compose up --build
```

> Note: kind's API server is usually `https://127.0.0.1:<port>`. From inside a container that address is the container itself, not your host. For Docker Compose on Windows or macOS, either run the controller on the host (Option A) or point kubeconfig at `https://host.docker.internal:<port>`.

##### Option C — in-cluster (RBAC included)

Apply least-privilege RBAC and run inside the cluster:

```bash
kubectl apply -f deploy/serviceaccount.yaml
kubectl apply -f deploy/clusterrole.yaml
kubectl apply -f deploy/clusterrolebinding.yaml

docker build -t kubeguardian:latest .
kind load docker-image kubeguardian:latest --name kubeguardian

kubectl apply -f deploy/deployment.yaml
kubectl logs -l app.kubernetes.io/name=kubeguardian -f
```

The ClusterRole grants only what the controller needs: watch/get/list/delete on pods, get on ReplicaSets, and get/patch on Deployments. Patch is required for Pending and Failed heals, while CrashLoopBackOff heals only delete the pod.

#### 4. Watch it heal

```bash
kubectl get pods -l app=crashloop-demo -w
curl http://localhost:8000/metrics | grep incidents_
```

| Run mode | How to view the log |
|---|---|
| Host (Option A) | `cat incidents.jsonl` (or your `INCIDENT_LOG_PATH`) |
| Docker Compose (Option B) | `docker compose exec controller cat /var/log/kubeguardian/incidents.jsonl` |
| In-cluster (Option C) | `kubectl logs -l app.kubernetes.io/name=kubeguardian` and check the mounted volume via exec |

You should see the crashloop pod deleted and recreated, metrics increment, and a JSON line in the incident log.

#### 5. Open dashboards

Start Prometheus and Grafana (works with host or Compose controller):

```bash
docker compose up prometheus grafana
```

| Service | URL | Credentials |
|---|---|---|
| Metrics | http://localhost:8000/metrics | — |
| Prometheus | http://localhost:9090 | — |
| Grafana | http://localhost:3000 | admin / admin |

Prometheus scrapes `controller:8000` when the controller runs in Docker Compose, and `host.docker.internal:8000` when the controller runs on the host.

## Configuration

Environment variables (see `controller/config.py`):

| Variable | Default | Description |
|---|---|---|
| `WATCH_NAMESPACES` | *(all)* | Comma-separated list, for example `default` |
| `PENDING_THRESHOLD_SECONDS` | `120` (`60` in Docker Compose) | Pending age before incident |
| `HEAL_COOLDOWN_SECONDS` | `300` (`120` in Docker Compose) | Minimum seconds between heals per workload |
| `POLL_INTERVAL` | `5` | Watch reconnect interval |
| `METRICS_PORT` | `8000` | Prometheus scrape port |
| `INCIDENT_LOG_PATH` | `/var/log/kubeguardian/incidents.jsonl` | JSON-lines log path |
| `LOG_LEVEL` | `INFO` | Python log level |

## Metrics and observability

| Metric | Labels | Description |
|---|---|---|
| `incidents_detected_total` | `namespace`, `reason` | Failures detected |
| `incidents_resolved_total` | `namespace`, `reason` | Successful remediations |
| `pod_restarts_total` | `namespace`, `action` | Actions taken (`delete_pod`, `rollout_restart`) |

Each line in `incidents.jsonl` follows this format:

```json
{"timestamp": "2026-07-01T12:00:00+00:00", "namespace": "default", "pod": "crashloop-demo-abc123", "reason": "CrashLoopBackOff", "action": "delete_pod", "resolved": true}
```

This file is a stand-in for PostgreSQL persistence in a later phase.

## Roadmap

Planned next phases (not in this build):

- PostgreSQL — durable incident store replacing JSON-lines log
- Helm chart — package the controller for in-cluster deployment
- GitHub Actions CI/CD — lint, test, and image publish on merge
- Slack or email alerting — notify on incidents and failed heals

## Development

```bash
pip install -r requirements-dev.txt
pytest
python -m controller.main
python scripts/generate_screenshots.py   # refresh README demo images
```

Unit tests cover pod failure detection, heal action routing, cooldown behavior, and Deployment ownership resolution.

## Contributing

This is a personal learning project, but issues and pull requests are welcome.

## License

MIT licensed. See [LICENSE](LICENSE).
