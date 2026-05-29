"""PROF-01 档案年龄区间计算。

提供 calculate_age_range() 纯函数，根据出生日期实时计算年龄区间枚举值。
"""

from __future__ import annotations

from datetime import date

from dateutil.relativedelta import relativedelta

from py_schemas.profiles import AgeRange


def calculate_age_range(birth_date: date) -> AgeRange:
    """根据出生日期实时计算年龄区间。

    使用 dateutil.relativedelta 计算精确年龄（考虑闰年），
    然后映射到 AgeRange 枚举值。

    Args:
        birth_date: 患者的出生日期。

    Returns:
        AgeRange: 对应的年龄区间枚举值。
    """
    age_years = relativedelta(date.today(), birth_date).years

    if age_years <= 3:
        return AgeRange.AGE_0_3
    elif age_years <= 6:
        return AgeRange.AGE_4_6
    elif age_years <= 12:
        return AgeRange.AGE_7_12
    elif age_years <= 18:
        return AgeRange.AGE_13_18
    else:
        return AgeRange.AGE_18_PLUS
