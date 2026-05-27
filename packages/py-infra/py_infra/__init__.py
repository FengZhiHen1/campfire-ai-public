"""py-infra: Infrastructure contract models and exceptions for Campfire-AI.

Exposes Pydantic models and enums corresponding to DEPLOY-01 JSON Schema contracts,
and CSLT-02 retrieval exception classes.
"""

from py_infra.exceptions import EmbeddingUnavailableError, RetrievalTimeoutError
from py_infra.models import (
    # Enums
    ContainerServiceName,
    DeploymentState,
    InternalDnsName,
    NamedVolume,
    ServiceRestartPolicy,
    # Models
    ComposeFileReference,
    ContainerNetwork,
    HealthCheckProbe,
    LogDriverConfig,
    PortMappingRule,
)

__all__ = [
    "ContainerServiceName",
    "DeploymentState",
    "InternalDnsName",
    "NamedVolume",
    "ServiceRestartPolicy",
    "ComposeFileReference",
    "ContainerNetwork",
    "HealthCheckProbe",
    "LogDriverConfig",
    "PortMappingRule",
    "RetrievalTimeoutError",
    "EmbeddingUnavailableError",
]
