#!/usr/bin/env python3
"""
time_utils - 时间处理公共工具
提供常用的时间格式化函数
"""

from datetime import datetime, timedelta
from typing import Optional


def today_str(fmt: str = "%Y-%m-%d") -> str:
    """返回今天的日期字符串"""
    return datetime.now().strftime(fmt)


def now_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """返回当前时间字符串"""
    return datetime.now().strftime(fmt)


def timestamp_str() -> str:
    """返回时间戳字符串（用于文件名）"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def days_ago(days: int, fmt: str = "%Y-%m-%d") -> str:
    """返回 N 天前的日期字符串"""
    return (datetime.now() - timedelta(days=days)).strftime(fmt)


def parse_date(date_str: str, fmt: str = "%Y-%m-%d") -> Optional[datetime]:
    """解析日期字符串"""
    try:
        return datetime.strptime(date_str, fmt)
    except Exception:
        return None


if __name__ == "__main__":
    # 测试
    print(f"今天: {today_str()}")
    print(f"现在: {now_str()}")
    print(f"时间戳: {timestamp_str()}")
    print(f"7天前: {days_ago(7)}")

    # 测试解析
    date = parse_date("2026-04-02")
    assert date is not None
    assert date.year == 2026
    assert date.month == 4
    assert date.day == 2

    print("\n✅ 所有测试通过！")
