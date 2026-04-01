#!/usr/bin/env python3
"""
file_utils - 文件操作公共工具
提供原子写入、安全读取等常用文件操作
"""

import os
from pathlib import Path
from typing import Union


def atomic_write(filepath: Union[str, Path], content: str, encoding: str = "utf-8"):
    """
    原子写入文件（临时文件 + 重命名）
    保证写入过程中不会损坏原文件
    """
    filepath = Path(filepath)
    tmp = filepath.with_suffix(filepath.suffix + ".tmp")

    try:
        # 确保父目录存在
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # 写入临时文件
        tmp.write_text(content, encoding=encoding)

        # 原子重命名
        os.replace(tmp, filepath)

    finally:
        # 清理临时文件
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass


def safe_read(filepath: Union[str, Path], default: str = "", encoding: str = "utf-8") -> str:
    """
    安全读取文件
    文件不存在或读取失败时返回默认值
    """
    try:
        return Path(filepath).read_text(encoding=encoding)
    except Exception:
        return default


def ensure_dir(dirpath: Union[str, Path]):
    """确保目录存在"""
    Path(dirpath).mkdir(parents=True, exist_ok=True)


def file_exists(filepath: Union[str, Path]) -> bool:
    """检查文件是否存在"""
    return Path(filepath).exists()


if __name__ == "__main__":
    import tempfile

    # 测试
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test.txt"

        # 测试原子写入
        print("测试原子写入...")
        atomic_write(test_file, "Hello, World!")
        assert test_file.read_text() == "Hello, World!"
        print("✅ 原子写入测试通过")

        # 测试安全读取
        print("\n测试安全读取...")
        content = safe_read(test_file)
        assert content == "Hello, World!"
        print("✅ 安全读取测试通过")

        # 测试不存在的文件
        print("\n测试不存在的文件...")
        content = safe_read(Path(tmpdir) / "nonexistent.txt", default="default")
        assert content == "default"
        print("✅ 默认值测试通过")

        print("\n✅ 所有测试通过！")
