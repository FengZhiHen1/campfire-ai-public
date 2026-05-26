"""Pydantic models and Python enums for DEPLOY-01 container orchestration contracts.

Each model/precision-enum corresponds to a JSON Schema contract in docs/contracts/DEPLOY-01/.
Field names, types, required/optional status, constraints (min/max, enum, const, default)
must match the contract exactly.
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


# ============================================================
# Enums (5 contracts)
# ============================================================


class ContainerServiceName(StrEnum):
    """Contract: ContainerServiceName.json — 6 container service name identifiers.

    Matches contract enum values exactly.
    """

    API_SERVER = "campfire-api-server"
    WORKER = "campfire-worker"
    POSTGRES = "campfire-postgres"
    REDIS = "campfire-redis"
    MINIO = "campfire-minio"
    NGINX = "campfire-nginx"


class InternalDnsName(StrEnum):
    """Contract: InternalDnsName.json — internal DNS name:port mappings.

    Matches contract enum values exactly.
    """

    API_SERVER = "api-server:8000"
    WORKER = "worker:8000"
    POSTGRES = "postgres:5432"
    REDIS = "redis:6379"
    MINIO = "minio:9000"
    NGINX = "nginx:80"


class NamedVolume(StrEnum):
    """Contract: NamedVolume.json — Docker named volume identifiers.

    Matches contract enum values exactly.
    """

    PGDATA = "pgdata"
    REDIS_DATA = "redis_data"
    MINIO_DATA = "minio_data"


class DeploymentState(StrEnum):
    """Contract: DeploymentState.json — container cluster business state enum.

    Matches contract enum values exactly.
    """

    STARTING = "STARTING"
    RUNNING = "RUNNING"
    ERROR = "ERROR"
    STOPPED = "STOPPED"


class ServiceRestartPolicy(StrEnum):
    """Contract: ServiceRestartPolicy.json — container restart policy enum (D15 compromise).

    Matches contract enum values exactly.
    """

    UNLESS_STOPPED_WITH_HEALTHCHECK_SAFETY = "unless-stopped_with_healthcheck_safety"


# ============================================================
# Pydantic Models (5 contracts)
# ============================================================


class ComposeFileReference(BaseModel):
    """Contract: ComposeFileReference.json — compose file selection reference.

    Used by DEPLOY-03 CI/CD pipeline to select the correct orchestration file per environment.
    """

    environment: Literal["dev", "prod"] = Field(
        description="Running environment identifier; determines which compose file to use",
    )
    file_path: str = Field(
        min_length=1,
        description="Relative path to compose file from project root",
        examples=["docker-compose.yml", "docker-compose.prod.yml"],
    )
    orchestration_scope: Literal["3_data_containers", "6_services"] = Field(
        description="Orchestration scope: dev=3_data_containers, prod=6_services",
    )

    model_config = {"extra": "forbid"}


class ContainerNetwork(BaseModel):
    """Contract: ContainerNetwork.json — prod custom bridge network config.

    Used by DEPLOY-02 (nginx routing) and DEPLOY-04 (database migration).
    """

    network_name: Literal["campfire-net"] = Field(
        description="Fixed name of the custom bridge network",
    )
    driver: Literal["bridge"] = Field(
        description="Docker network driver type, fixed as bridge",
    )
    scope: Literal["prod_only"] = Field(
        description="Network scope: only prod uses campfire-net; dev uses default bridge",
    )
    dns_resolution: Literal[True] = Field(
        description="Internal DNS resolution flag; true means service name resolves to container IP",
    )
    external: bool = Field(
        default=False,
        description="Whether the network is pre-created externally; false means compose auto-creates it",
    )

    model_config = {"extra": "forbid"}


class HealthCheckProbe(BaseModel):
    """Contract: HealthCheckProbe.json — Docker HEALTHCHECK probe configuration.

    Used by OBS-04 for health-check observability integration.
    """

    service: ContainerServiceName = Field(
        description="Service name; must be one of the 6 defined container services",
    )
    test_command: str = Field(
        min_length=1,
        description="HEALTHCHECK probe command string per service",
        examples=[
            "curl -f http://localhost:8000/health",
            "pg_isready -U campfire",
            "redis-cli ping",
        ],
    )
    interval: str = Field(
        default="30s",
        min_length=1,
        description="Probe interval",
        examples=["30s"],
    )
    timeout: str = Field(
        default="10s",
        min_length=1,
        description="Single probe timeout",
        examples=["10s"],
    )
    retries: int = Field(
        default=3,
        strict=True,
        ge=1,
        le=10,
        description="Consecutive failure retry count; after exceeding, container marked unhealthy",
    )
    start_period: str = Field(
        default="0s",
        min_length=1,
        description="Grace period after start; failures during this period do not count toward retries",
        examples=["60s", "0s"],
    )

    model_config = {"extra": "forbid"}


class LogDriverConfig(BaseModel):
    """Contract: LogDriverConfig.json — Docker log driver and retention config.

    Used by OBS-01 to extract structured logs from container stdout/stderr.
    """

    driver: Literal["json-file"] = Field(
        description="Docker log driver type, fixed as json-file",
    )
    max_size: str = Field(
        min_length=1,
        description="Max size per log file; dev=10m, prod=20m",
        examples=["10m", "20m"],
    )
    max_file: int = Field(
        strict=True,
        description="Max number of log files retained; dev=3, prod=5",
        examples=[3, 5],
    )
    retention_days: int | None = Field(
        default=None,
        strict=True,
        description="Log retention in days; dev=7, prod controlled by max_size * max_file",
        examples=[7],
    )

    model_config = {"extra": "forbid"}


class PortMappingRule(BaseModel):
    """Contract: PortMappingRule.json — container-to-host port mapping rule.

    Used by DEPLOY-02 (reverse proxy routing) and SEC-01 (transport security).
    """

    environment: Literal["dev", "prod"] = Field(
        description="Environment: dev exposes all ports for debugging; prod only nginx 80/443",
    )
    service: ContainerServiceName = Field(
        description="Service name; must be one of the 6 defined container services",
    )
    host_port: int = Field(
        strict=True,
        ge=1,
        le=65535,
        description="Host listening port",
        examples=[8000, 8080, 80, 5432, 6379, 9000],
    )
    container_port: int = Field(
        strict=True,
        ge=1,
        le=65535,
        description="Container internal listening port",
        examples=[8000, 5432, 6379, 9000, 80],
    )
    protocol: Literal["tcp", "udp"] = Field(
        default="tcp",
        description="Transport layer protocol, defaults to tcp",
    )

    model_config = {"extra": "forbid"}
