#!/usr/bin/env python3
"""
json_utils - JSON 处理公共工具
提供统一的 JSON 序列化/反序列化函数
"""

import json
from pathlib import Path
from typing import Any, Union


def dump_json(data: Any, ensure_ascii: bool = False, indent: int = 2) -> str:
    """序列化为 JSON 字符串"""
    return json.dumps(data, ensure_ascii=ensure_ascii, indent=indent)


def load_json(filepath: Union[str, Path], default: Any = None) -> Any:
    """从文件加载 JSON"""
    try:
        return json.loads(Path(filepath).read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(filepath: Union[str, Path], data: Any, ensure_ascii: bool = False, indent: int = 2):
    """保存 JSON 到文件"""
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(dump_json(data, ensure_ascii, indent), encoding="utf-8")


def parse_json(json_str: str, default: Any = None) -> Any:
    """解析 JSON 字符串"""
    try:
        return json.loads(json_str)
    except Exception:
        return default


if __name__ == "__main__":
    import tempfile

    # 测试
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test.json"

        # 测试序列化
        print("测试序列化...")
        data = {"name": "测试", "value": 123, "list": [1, 2, 3]}
        json_str = dump_json(data)
        assert "测试" in json_str
        print("✅ 序列化测试通过")

        # 测试保存
        print("\n测试保存...")
        save_json(test_file, data)
        assert test_file.exists()
        print("✅ 保存测试通过")

        # 测试加载
        print("\n测试加载...")
        loaded = load_json(test_file)
        assert loaded == data
        print("✅ 加载测试通过")

        # 测试解析
        print("\n测试解析...")
        parsed = parse_json(json_str)
        assert parsed == data
        print("✅ 解析测试通过")

        # 测试不存在的文件
        print("\n测试不存在的文件...")
        loaded = load_json(Path(tmpdir) / "nonexistent.json", default={})
        assert loaded == {}
        print("✅ 默认值测试通过")

        print("\n✅ 所有测试通过！")
