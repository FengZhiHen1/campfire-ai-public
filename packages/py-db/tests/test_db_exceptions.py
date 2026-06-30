"""DEPLOY-04 数据库迁移 + SEC-05 Repository 异常 — 单元测试。"""

from __future__ import annotations

from py_db.exceptions import (
    MigrationConnectionError,
    MigrationExecutionError,
    MigrationGenerationError,
    MigrationRollbackError,
    MigrationScriptNotFoundError,
    MigrationVerificationError,
)
from py_db.repositories.base_repository import DependencyCommunicationError


class TestMigrationExecutionError:
    def test_basic(self):
        e = MigrationExecutionError("执行失败", script_name="abc.py", revision_id="rev1")
        assert e.error_code == "MIG-ERR-001"
        assert e.script_name == "abc.py"
        assert str(e) == "执行失败"


class TestMigrationRollbackError:
    def test_basic(self):
        e = MigrationRollbackError("回滚失败", current_version="v1")
        assert e.error_code == "MIG-ERR-002"
        assert e.current_version == "v1"


class TestMigrationConnectionError:
    def test_basic(self):
        e = MigrationConnectionError("连接不可用", retries_attempted=3)
        assert e.error_code == "MIG-ERR-003"
        assert e.retries_attempted == 3


class TestMigrationScriptNotFoundError:
    def test_basic(self):
        e = MigrationScriptNotFoundError("版本不存在", target="abc123")
        assert e.target == "abc123"


class TestMigrationGenerationError:
    def test_basic(self):
        e = MigrationGenerationError("生成失败")
        assert e.message == "生成失败"


class TestMigrationVerificationError:
    def test_basic(self):
        e = MigrationVerificationError("验证错误")
        assert e.message == "验证错误"


class TestDependencyCommunicationError:
    def test_basic(self):
        e = DependencyCommunicationError("数据库不可达")
        assert "数据库不可达" in str(e)
        assert isinstance(e, Exception)
