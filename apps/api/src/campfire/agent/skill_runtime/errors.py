"""skill 机制的错误类型。

集中定义是为了让「不合法即拒绝加载」这条纪律只有一个失败形状：调用方捕获
``SkillError`` 即可区分「skill 内容有问题」与「基础设施出错」，不必认识每个细节。

依据 docs/技术设计/technical-details/通用基座.md 第 3 节与第 9 节：frontmatter
不合法必须**拒绝加载并在启动/校验时报错**，不得以空元数据静默加载。
"""

from __future__ import annotations


class SkillError(Exception):
    """skill 机制的基类错误。"""


class SkillFrontmatterError(SkillError):
    """frontmatter 不合法：缺字段、类型不符、自创字段、超长或重复键。

    ``detail`` 面向 skill 作者，必须指明「期望形状」而不只是「错了」。
    """

    def __init__(self, path: str, detail: str) -> None:
        """记录出问题的文件路径与面向作者的说明。"""
        self.path = path
        self.detail = detail
        super().__init__(f"{path}: {detail}")


class SkillDiscoveryError(SkillError):
    """发现阶段的结构性问题。

    既用于根目录本身不可用，也用于聚合多个 skill 的 frontmatter 错误——一次加载
    把所有问题都报出来，而不是改一个报一个。
    """

    def __init__(self, detail: str, *, problems: tuple[str, ...] = ()) -> None:
        """记录总体结论与逐条明细。"""
        self.detail = detail
        self.problems = problems
        super().__init__(detail if not problems else detail + "\n" + "\n".join(problems))


class SkillNotFoundError(SkillError):
    """按名字取 skill 时不存在。

    这是**可恢复**错误：模型调用 ``skill({name})`` 传了未注册的名字时，它应当作为
    工具结果回给模型（见基座文档第 5 节失败语义），而不是中断本次运行。
    """

    def __init__(self, name: str, known: tuple[str, ...]) -> None:
        """记录请求的名字与当前已注册的名字，便于调用方直接回给模型。"""
        self.name = name
        self.known = known
        super().__init__(f"未注册的 skill：{name}（已注册：{', '.join(known) or '无'}）")


class SkillCatalogOverflowError(SkillError):
    """技能目录超出预算，且按面筛选后仍然超出。

    不截断、不静默丢弃（基座文档第 9 节：不得静默降级），而是让装配处显式处理。
    """


class SkillResourceError(SkillError):
    """资源读取被拒绝：越界路径、层级过深、不是文件、非 UTF-8 或超出体积上限。"""
