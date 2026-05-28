"""DEPLOY-01 容器编排 — 模型与枚举单元测试。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from py_infra.models import (
    ComposeFileReference,
    ContainerNetwork,
    ContainerServiceName,
    DeploymentState,
    HealthCheckProbe,
    InternalDnsName,
    LogDriverConfig,
    NamedVolume,
    PortMappingRule,
    ServiceRestartPolicy,
)


class TestContainerServiceName:
    def test_values(self):
        assert ContainerServiceName.API_SERVER == "campfire-api-server"
        assert ContainerServiceName.POSTGRES == "campfire-postgres"
        assert ContainerServiceName.NGINX == "campfire-nginx"


class TestInternalDnsName:
    def test_values(self):
        assert InternalDnsName.API_SERVER == "api-server:8000"
        assert InternalDnsName.POSTGRES == "postgres:5432"


class TestDeploymentState:
    def test_values(self):
        assert DeploymentState.STARTING == "STARTING"
        assert DeploymentState.RUNNING == "RUNNING"
        assert DeploymentState.ERROR == "ERROR"


class TestComposeFileReference:
    def test_valid(self):
        ref = ComposeFileReference(
            environment="dev",
            file_path="docker-compose.yml",
            orchestration_scope="3_data_containers",
        )
        assert ref.environment == "dev"

    def test_invalid_environment(self):
        with pytest.raises(ValidationError):
            ComposeFileReference(
                environment="staging",
                file_path="docker-compose.yml",
                orchestration_scope="3_data_containers",
            )


class TestContainerNetwork:
    def test_defaults(self):
        net = ContainerNetwork(
            network_name="campfire-net",
            driver="bridge",
            scope="prod_only",
            dns_resolution=True,
        )
        assert net.external is False


class TestHealthCheckProbe:
    def test_valid(self):
        probe = HealthCheckProbe(
            service=ContainerServiceName.API_SERVER,
            test_command="curl -f http://localhost:8000/health",
        )
        assert probe.interval == "30s"
        assert probe.retries == 3

    def test_retries_out_of_range(self):
        with pytest.raises(ValidationError):
            HealthCheckProbe(
                service=ContainerServiceName.API_SERVER,
                test_command="curl -f http://localhost:8000/health",
                retries=20,
            )


class TestPortMappingRule:
    def test_valid(self):
        rule = PortMappingRule(
            environment="dev",
            service=ContainerServiceName.API_SERVER,
            host_port=8000,
            container_port=8000,
        )
        assert rule.protocol == "tcp"

    def test_invalid_port(self):
        with pytest.raises(ValidationError):
            PortMappingRule(
                environment="dev",
                service=ContainerServiceName.API_SERVER,
                host_port=99999,
                container_port=8000,
            )


class TestLogDriverConfig:
    def test_valid(self):
        cfg = LogDriverConfig(driver="json-file", max_size="10m", max_file=3)
        assert cfg.driver == "json-file"
