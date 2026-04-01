#!/usr/bin/env python3
"""
AutoStateManager - 自动状态管理器
在 StateManager 基础上添加全自动维护功能

特性：
- 自动触发状态清理
- 自动备份
- 自动健康检查
- 低Token消耗：懒加载 + 缓存
"""

import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, List

from .state_manager import StateManager

WORKSPACE = Path(
    os.environ.get("OPENCLAW_WORKSPACE", Path(__file__).parent.parent.parent)
)


class AutoStateManager(StateManager):
    """增强版状态管理器，支持全自动操作"""

    def __init__(self, workspace: Path = None):
        super().__init__(workspace)
        self._last_cleanup = None
        self._last_backup = None
        self._last_health_check = None

        # 加载上次运行时间
        self._load_last_run_times()

    def _load_last_run_times(self):
        """加载上次运行时间"""
        last_run_file = self.workspace / "state" / "auto_manager_last_run.json"
        if last_run_file.exists():
            try:
                import json

                data = json.loads(last_run_file.read_text(encoding="utf-8"))
                if data.get("last_cleanup"):
                    self._last_cleanup = datetime.fromisoformat(data["last_cleanup"])
                if data.get("last_backup"):
                    self._last_backup = datetime.fromisoformat(data["last_backup"])
                if data.get("last_health_check"):
                    self._last_health_check = datetime.fromisoformat(
                        data["last_health_check"]
                    )
            except Exception:
                pass

    def _save_last_run_times(self):
        """保存上次运行时间"""
        import json

        last_run_file = self.workspace / "state" / "auto_manager_last_run.json"
        data = {
            "last_cleanup": self._last_cleanup.isoformat()
            if self._last_cleanup
            else None,
            "last_backup": self._last_backup.isoformat() if self._last_backup else None,
            "last_health_check": self._last_health_check.isoformat()
            if self._last_health_check
            else None,
        }
        last_run_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def get(self, path: str, default: Any = None) -> Any:
        """获取状态时自动触发维护检查"""
        self._auto_maintain()
        return super().get(path, default)

    def set(self, path: str, value: Any, atomic: bool = True):
        """设置状态时自动触发维护检查"""
        super().set(path, value, atomic)
        self._auto_maintain()

    def _auto_maintain(self):
        """自动维护检查"""
        now = datetime.now()

        # 每小时清理一次
        if self._should_run(self._last_cleanup, hours=1):
            self.cleanup(days=30)
            self._last_cleanup = now
            self._save_last_run_times()

        # 每6小时备份一次
        if self._should_run(self._last_backup, hours=6):
            self.backup()
            self._last_backup = now
            self._save_last_run_times()

        # 每30分钟健康检查一次
        if self._should_run(self._last_health_check, minutes=30):
            self._health_check()
            self._last_health_check = now
            self._save_last_run_times()

    def _should_run(self, last_run: datetime, **timedelta_kwargs) -> bool:
        """判断是否应该执行"""
        if last_run is None:
            return True
        return datetime.now() - last_run > timedelta(**timedelta_kwargs)

    def _health_check(self):
        """自动健康检查"""
        summary = self.get_summary()

        # 检查关键指标
        issues = []
        if summary["active_violations"] > 10:
            issues.append(f"违规过多: {summary['active_violations']}")

        if summary["health_status"] != "healthy":
            issues.append(f"健康状态异常: {summary['health_status']}")

        # 记录问题
        if issues:
            self.append(
                "system.errors",
                {
                    "timestamp": datetime.now().isoformat(),
                    "type": "health_check",
                    "issues": issues,
                },
                max_items=100,
            )


class TokenOptimizer:
    """Token消耗优化器"""

    # 关键状态路径（每次会话必须加载）
    ESSENTIAL_PATHS = [
        "sessions.current",
        "system.health.status",
        "rules.violations",  # 只加载最近10条
    ]

    # 可延迟加载的路径（按需加载）
    DEFERRABLE_PATHS = [
        "learning.knowledge_map",
        "learning.crystallized_knowledge",
        "system.operations",
    ]

    def __init__(self, state_manager: StateManager):
        self.state = state_manager
        self._loaded_paths = set()

    def load_essential(self) -> Dict:
        """加载关键状态（每次会话开始时调用）"""
        essential = {}
        for path in self.ESSENTIAL_PATHS:
            value = self.state.get(path)
            if value is not None:
                # 对于列表，只返回最近的条目
                if isinstance(value, list) and len(value) > 10:
                    value = value[-10:]
                essential[path] = value
                self._loaded_paths.add(path)
        return essential

    def load_on_demand(self, path: str) -> Any:
        """按需加载（只在需要时加载）"""
        if path in self._loaded_paths:
            return self.state.get(path)

        value = self.state.get(path)
        self._loaded_paths.add(path)

        # 对于大型数据，返回摘要
        if isinstance(value, dict) and len(value) > 20:
            return self._summarize_dict(value)
        if isinstance(value, list) and len(value) > 50:
            return value[-50:]  # 只返回最近50条

        return value

    def _summarize_dict(self, data: Dict) -> Dict:
        """字典摘要"""
        return {"keys": list(data.keys())[:20], "count": len(data), "_summarized": True}

    def get_context_for_llm(self) -> str:
        """获取用于LLM的上下文（最小化Token）"""
        essential = self.load_essential()

        # 构建最小上下文
        context_parts = []

        # 会话信息
        session = essential.get("sessions.current", {})
        if session:
            context_parts.append(f"会话类型: {session.get('type', 'none')}")

        # 健康状态
        health = essential.get("system.health.status", "unknown")
        if health != "healthy":
            context_parts.append(f"⚠️ 系统状态: {health}")

        # 最近违规
        violations = essential.get("rules.violations", [])
        if violations:
            recent = violations[-3:]  # 只取最近3条
            for v in recent:
                context_parts.append(f"违规: {v.get('rule_id', 'unknown')}")

        return "\n".join(context_parts) if context_parts else "系统正常"


# 全局实例
_auto_state_manager = None


def get_auto_state_manager() -> AutoStateManager:
    """获取全局自动状态管理器实例"""
    global _auto_state_manager
    if _auto_state_manager is None:
        _auto_state_manager = AutoStateManager()
    return _auto_state_manager


if __name__ == "__main__":
    # 测试
    manager = AutoStateManager()

    # 测试基本操作
    manager.set("test.auto", "value")
    assert manager.get("test.auto") == "value"

    # 测试Token优化器
    optimizer = TokenOptimizer(manager)
    essential = optimizer.load_essential()
    print(f"✅ 关键状态: {essential}")

    context = optimizer.get_context_for_llm()
    print(f"✅ LLM上下文:\n{context}")
