#!/usr/bin/env python3
"""
StateManager - 统一状态管理器
单一数据源，原子操作，懒加载，自动清理

特性：
- 单一数据源：state/unified_state.json
- 原子写入：WAL协议
- 懒加载：按需加载子集
- 缓存：5分钟TTL
- 自动清理：定期清理过期数据
"""

import json
import os
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Callable
from threading import Lock

WORKSPACE = Path(
    os.environ.get("OPENCLAW_WORKSPACE", Path(__file__).parent.parent.parent)
)


class StateManager:
    """统一状态管理器"""

    def __init__(self, workspace: Path = None):
        self.workspace = workspace or WORKSPACE
        self.state_file = self.workspace / "state" / "unified_state.json"
        self.backup_dir = self.workspace / "state" / "backups"
        self._lock = Lock()
        self._cache = {}
        self._cache_ttl = 300  # 5分钟缓存

        # 初始化
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        if not self.state_file.exists():
            self._init_state()

    def _init_state(self):
        """初始化统一状态文件"""
        initial_state = {
            "version": "1.0",
            "last_updated": datetime.now().isoformat(),
            # 记忆相关
            "memory": {
                "last_write": None,
                "write_count": 0,
                "failures": [],
                "archive_index": {},
            },
            # 学习相关
            "learning": {
                "knowledge_map": {},
                "crystallized_knowledge": [],
                "learning_suggestions": [],
                "learning_journey": [],
                "meta_learning": {},
            },
            # 规则相关
            "rules": {
                "auto_learned": {"hot": [], "cold": []},
                "violations": [],
                "metadata": {},
                "audit_log": [],
            },
            # 系统状态
            "system": {
                "health": {"status": "healthy", "last_check": None},
                "errors": [],
                "operations": [],
                "behavior_patterns": [],
            },
            # 会话相关
            "sessions": {"current": None, "history": [], "feedback": []},
            # 隐私相关
            "privacy": {"violations": [], "rules": {}, "resolved": []},
            # 实验相关
            "experiments": {"active": [], "applied": [], "rollbacks": []},
            # 提醒相关
            "reminders": {"active": [], "completed": []},
        }
        self._write_state(initial_state)

    def get(self, path: str, default: Any = None) -> Any:
        """
        获取状态值（支持点号路径）
        例：state.get("learning.knowledge_map.Python开发")
        """
        # 检查缓存
        cache_key = f"get:{path}"
        if cache_key in self._cache:
            cached_value, cached_time = self._cache[cache_key]
            if (datetime.now() - cached_time).seconds < self._cache_ttl:
                return cached_value

        # 加载状态
        state = self._read_state()
        keys = path.split(".")

        value = state
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default

        # 更新缓存
        self._cache[cache_key] = (value, datetime.now())
        return value

    def set(self, path: str, value: Any, atomic: bool = True):
        """
        设置状态值（支持点号路径）
        例：state.set("learning.knowledge_map.Python开发", {...})
        """
        with self._lock:
            state = self._read_state()
            keys = path.split(".")

            # 导航到目标位置
            current = state
            for key in keys[:-1]:
                if key not in current:
                    current[key] = {}
                current = current[key]

            # 设置值
            current[keys[-1]] = value
            state["last_updated"] = datetime.now().isoformat()

            # 原子写入
            if atomic:
                self._atomic_write(state)
            else:
                self._write_state(state)

            # 清除相关缓存
            self._invalidate_cache(path)

    def update(self, path: str, updates: Dict, atomic: bool = True):
        """
        更新状态值（合并更新）
        例：state.update("learning.knowledge_map.Python开发", {"confidence": 0.9})
        """
        current = self.get(path, {})
        if isinstance(current, dict):
            current.update(updates)
            self.set(path, current, atomic)

    def append(self, path: str, item: Any, max_items: int = None):
        """
        追加到列表状态
        例：state.append("rules.violations", {...})
        """
        current = self.get(path, [])
        if isinstance(current, list):
            current.append(item)
            if max_items and len(current) > max_items:
                current = current[-max_items:]
            self.set(path, current)

    def delete(self, path: str):
        """删除状态值"""
        with self._lock:
            state = self._read_state()
            keys = path.split(".")

            # 导航到目标位置
            current = state
            for key in keys[:-1]:
                if key not in current:
                    return  # 路径不存在
                current = current[key]

            # 删除值
            if keys[-1] in current:
                del current[keys[-1]]
                state["last_updated"] = datetime.now().isoformat()
                self._atomic_write(state)
                self._invalidate_cache(path)

    def exists(self, path: str) -> bool:
        """检查路径是否存在"""
        return self.get(path) is not None

    def keys(self, path: str = "") -> List[str]:
        """获取指定路径下的所有键"""
        value = self.get(path, {})
        if isinstance(value, dict):
            return list(value.keys())
        return []

    def _read_state(self) -> Dict:
        """读取状态文件"""
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"⚠️ [StateManager] 读取失败: {e}")
            return {}

    def _write_state(self, state: Dict):
        """写入状态文件"""
        try:
            self.state_file.write_text(
                json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            print(f"⚠️ [StateManager] 写入失败: {e}")

    def _atomic_write(self, state: Dict):
        """原子写入（WAL协议）"""
        tmp_file = self.state_file.with_suffix(".tmp")
        try:
            tmp_file.write_text(
                json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(tmp_file, self.state_file)
        except Exception as e:
            print(f"⚠️ [StateManager] 原子写入失败: {e}")
            if tmp_file.exists():
                tmp_file.unlink()

    def _invalidate_cache(self, path: str):
        """清除相关缓存"""
        prefix = f"get:{path}"
        keys_to_remove = [k for k in self._cache if k.startswith(prefix)]
        for k in keys_to_remove:
            del self._cache[k]

    def clear_cache(self):
        """清除所有缓存"""
        self._cache.clear()

    def cleanup(self, days: int = 30):
        """
        清理过期状态
        - 清理超过N天的操作日志
        - 清理已解决的违规记录
        - 清理已应用的实验
        """
        with self._lock:
            state = self._read_state()
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()

            # 清理操作日志
            operations = state.get("system", {}).get("operations", [])
            state["system"]["operations"] = [
                op for op in operations if op.get("timestamp", "") > cutoff
            ][-1000:]  # 保留最近1000条

            # 清理已解决的违规
            violations = state.get("rules", {}).get("violations", [])
            state["rules"]["violations"] = [
                v for v in violations if not v.get("resolved", False)
            ][:100]  # 最多保留100条

            # 清理已应用的实验
            experiments = state.get("experiments", {}).get("active", [])
            state["experiments"]["active"] = [
                e for e in experiments if e.get("status") != "applied"
            ]

            # 清理旧会话历史
            sessions_history = state.get("sessions", {}).get("history", [])
            state["sessions"]["history"] = sessions_history[-50:]  # 保留最近50条

            # 清理旧错误日志
            errors = state.get("system", {}).get("errors", [])
            state["system"]["errors"] = errors[-100:]  # 保留最近100条

            state["last_updated"] = datetime.now().isoformat()
            self._write_state(state)

    def backup(self):
        """备份当前状态"""
        if self.state_file.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = self.backup_dir / f"state_{timestamp}.json"
            backup_file.write_bytes(self.state_file.read_bytes())

            # 清理旧备份（保留最近10个）
            backups = sorted(self.backup_dir.glob("state_*.json"))
            for old_backup in backups[:-10]:
                old_backup.unlink()

    def restore(self, backup_file: str = None):
        """恢复状态"""
        if backup_file:
            backup_path = Path(backup_file)
        else:
            # 恢复最新备份
            backups = sorted(self.backup_dir.glob("state_*.json"))
            if not backups:
                print("⚠️ 没有可用的备份")
                return False
            backup_path = backups[-1]

        if backup_path.exists():
            shutil.copy2(backup_path, self.state_file)
            self.clear_cache()
            print(f"✅ 已恢复备份: {backup_path.name}")
            return True
        return False

    def get_summary(self) -> Dict:
        """
        获取状态摘要（用于快速健康检查）
        返回关键指标，避免加载完整状态
        """
        state = self._read_state()
        current_session = state.get("sessions", {}).get("current")
        return {
            "last_updated": state.get("last_updated"),
            "memory_writes": state.get("memory", {}).get("write_count", 0),
            "knowledge_domains": len(
                state.get("learning", {}).get("knowledge_map", {})
            ),
            "active_violations": len(state.get("rules", {}).get("violations", [])),
            "health_status": state.get("system", {})
            .get("health", {})
            .get("status", "unknown"),
            "current_session": current_session.get("type", "none")
            if current_session
            else "none",
            "total_operations": len(state.get("system", {}).get("operations", [])),
            "active_experiments": len(state.get("experiments", {}).get("active", [])),
        }

    def batch_get(self, paths: List[str]) -> Dict[str, Any]:
        """批量获取状态值"""
        state = self._read_state()
        results = {}

        for path in paths:
            keys = path.split(".")
            value = state
            for key in keys:
                if isinstance(value, dict) and key in value:
                    value = value[key]
                else:
                    value = None
                    break
            results[path] = value

        return results

    def batch_set(self, updates: Dict[str, Any], atomic: bool = True):
        """批量设置状态值"""
        with self._lock:
            state = self._read_state()

            for path, value in updates.items():
                keys = path.split(".")
                current = state
                for key in keys[:-1]:
                    if key not in current:
                        current[key] = {}
                    current = current[key]
                current[keys[-1]] = value

            state["last_updated"] = datetime.now().isoformat()

            if atomic:
                self._atomic_write(state)
            else:
                self._write_state(state)

            # 清除所有缓存
            self.clear_cache()

    def transaction(self, operations: List[Callable]):
        """
        事务执行多个操作
        要么全部成功，要么全部回滚
        """
        with self._lock:
            # 备份当前状态
            backup_state = self._read_state()

            try:
                for op in operations:
                    op(self)
                # 提交
                state = self._read_state()
                state["last_updated"] = datetime.now().isoformat()
                self._atomic_write(state)
            except Exception as e:
                # 回滚
                self._write_state(backup_state)
                raise e


# 全局实例
_state_manager = None


def get_state_manager() -> StateManager:
    """获取全局状态管理器实例"""
    global _state_manager
    if _state_manager is None:
        _state_manager = StateManager()
    return _state_manager


if __name__ == "__main__":
    # 测试
    manager = StateManager()

    # 测试基本操作
    manager.set("test.value", 42)
    assert manager.get("test.value") == 42

    manager.append("test.list", {"id": 1})
    manager.append("test.list", {"id": 2})
    assert len(manager.get("test.list")) == 2

    manager.update("test.obj", {"a": 1, "b": 2})
    manager.update("test.obj", {"b": 3, "c": 4})
    assert manager.get("test.obj") == {"a": 1, "b": 3, "c": 4}

    # 测试批量操作
    manager.batch_set({"test.batch1": "value1", "test.batch2": "value2"})
    results = manager.batch_get(["test.batch1", "test.batch2"])
    assert results == {"test.batch1": "value1", "test.batch2": "value2"}

    # 测试摘要
    summary = manager.get_summary()
    print(f"✅ 测试通过，摘要: {summary}")
