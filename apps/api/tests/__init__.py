"""测试包标记：让 `apps/api/tests` 成为真正的包。

为什么必须有这个文件（不是可有可无的装饰）：测试里用相对导入取会话夹具
（`from .conftest import connect_falkordb_or_skip`），而 pytest 的 importlib 模式
本来就按包路径装载这些模块（实测 `__name__` 为 `apps.api.tests.test_x`）。没有
`__init__.py` 时 mypy 把每个测试文件当成顶层模块，相对导入因此解析不到父包，
报 `Cannot find implementation or library stub for module named ".conftest"`——
那是配置与目录形状的问题，不是代码问题，加标记比逐处 ignore 更接近事实。
"""
