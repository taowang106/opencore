#!/usr/bin/env python3
"""
outcome_tracker.py - 效果追踪系统
合并track_outcome、feedback_loop、suggestion_tracker、suggestion_scorer、suggestion_applier

特性：
- 建议→应用→验证→反馈 完整闭环
- 自动质量评分
- 效果追踪
- 低Token消耗
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.state_manager import get_state_manager

WORKSPACE = Path(
    os.environ.get("OPENCLAW_WORKSPACE", Path(__file__).parent.parent.parent)
)


class OutcomeTracker:
    """效果追踪系统"""

    def __init__(self):
        self.state = get_state_manager()

    # ============================================================
    # 建议管理
    # ============================================================

    def create_suggestion(self, suggestion: Dict) -> str:
        """创建新建议"""
        suggestions = self.state.get("learning.learning_suggestions", [])

        # 生成ID
        suggestion_id = (
            f"sugg_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(suggestions)}"
        )

        suggestion["id"] = suggestion_id
        suggestion["created"] = datetime.now().isoformat()
        suggestion["status"] = "pending"
        suggestion["quality_score"] = 0
        suggestion["applied"] = False
        suggestion["verified"] = False

        suggestions.append(suggestion)

        # 限制数量，保留最近100个
        if len(suggestions) > 100:
            suggestions = suggestions[-100:]

        self.state.set("learning.learning_suggestions", suggestions)

        return suggestion_id

    def apply_suggestion(self, suggestion_id: str) -> Dict:
        """应用建议"""
        suggestions = self.state.get("learning.learning_suggestions", [])

        for sugg in suggestions:
            if sugg.get("id") == suggestion_id:
                # 应用建议
                result = self._apply_suggestion_logic(sugg)

                # 更新状态
                sugg["applied"] = True
                sugg["applied_at"] = datetime.now().isoformat()
                sugg["apply_result"] = result

                self.state.set("learning.learning_suggestions", suggestions)

                return result

        return {"success": False, "error": "Suggestion not found"}

    def verify_suggestion(self, suggestion_id: str, improvement: float) -> Dict:
        """验证建议效果"""
        suggestions = self.state.get("learning.learning_suggestions", [])

        for sugg in suggestions:
            if sugg.get("id") == suggestion_id:
                # 计算质量分数
                quality_score = self._calculate_quality_score(sugg, improvement)

                # 更新状态
                sugg["verified"] = True
                sugg["verified_at"] = datetime.now().isoformat()
                sugg["improvement"] = improvement
                sugg["quality_score"] = quality_score

                # 决定是否保留
                if quality_score >= 70:
                    sugg["status"] = "approved"
                else:
                    sugg["status"] = "rejected"

                self.state.set("learning.learning_suggestions", suggestions)

                # 记录反馈
                self._record_feedback(
                    {
                        "suggestion_id": suggestion_id,
                        "improvement": improvement,
                        "quality_score": quality_score,
                        "status": sugg["status"],
                    }
                )

                return {
                    "verified": True,
                    "quality_score": quality_score,
                    "status": sugg["status"],
                }

        return {"verified": False, "error": "Suggestion not found"}

    # ============================================================
    # 效果追踪
    # ============================================================

    def track_outcome(self, operation: Dict, outcome: Dict):
        """追踪操作结果"""
        outcomes = self.state.get("sessions.feedback", [])

        outcome["timestamp"] = datetime.now().isoformat()
        outcome["operation"] = operation

        outcomes.append(outcome)

        # 限制数量，保留最近100个
        if len(outcomes) > 100:
            outcomes = outcomes[-100:]

        self.state.set("sessions.feedback", outcomes)

        # 如果是失败，触发学习
        if not outcome.get("success", True):
            self._on_failure_tracked(operation, outcome)

    def get_outcome_stats(self) -> Dict:
        """获取结果统计"""
        outcomes = self.state.get("sessions.feedback", [])

        if not outcomes:
            return {"total": 0, "success_rate": 0, "avg_improvement": 0}

        total = len(outcomes)
        success = sum(1 for o in outcomes if o.get("success", True))

        improvements = [o.get("improvement", 0) for o in outcomes if "improvement" in o]
        avg_improvement = sum(improvements) / len(improvements) if improvements else 0

        return {
            "total": total,
            "success_rate": (success / total) * 100 if total > 0 else 0,
            "avg_improvement": avg_improvement,
        }

    # ============================================================
    # 反馈循环
    # ============================================================

    def feedback_loop(self, suggestion: Dict) -> Dict:
        """完整反馈闭环：建议→应用→验证→反馈"""
        # 1. 创建建议
        suggestion_id = self.create_suggestion(suggestion)

        # 2. 应用建议
        apply_result = self.apply_suggestion(suggestion_id)

        if not apply_result.get("success"):
            return {
                "suggestion_id": suggestion_id,
                "applied": False,
                "error": apply_result.get("error"),
            }

        # 3. 验证效果（如果有改进数据）
        improvement = apply_result.get("improvement", 0)
        verify_result = self.verify_suggestion(suggestion_id, improvement)

        return {
            "suggestion_id": suggestion_id,
            "applied": True,
            "verified": verify_result.get("verified"),
            "quality_score": verify_result.get("quality_score"),
            "status": verify_result.get("status"),
        }

    def get_feedback_stats(self) -> Dict:
        """获取反馈统计"""
        feedback_file = WORKSPACE / "state" / "feedback_loop.json"

        if not feedback_file.exists():
            return {"total": 0, "verified": 0, "avg_quality": 0}

        try:
            data = json.loads(feedback_file.read_text(encoding="utf-8"))
            feedbacks = data.get("feedbacks", [])

            if not feedbacks:
                return {"total": 0, "verified": 0, "avg_quality": 0}

            return {
                "total": len(feedbacks),
                "verified": len([f for f in feedbacks if f.get("verified")]),
                "avg_quality": sum(f.get("quality_score", 0) for f in feedbacks)
                / len(feedbacks),
            }
        except Exception:
            return {"total": 0, "verified": 0, "avg_quality": 0}

    # ============================================================
    # 内部方法
    # ============================================================

    def _apply_suggestion_logic(self, suggestion: Dict) -> Dict:
        """应用建议的具体逻辑"""
        # 这里应该实现具体的应用逻辑
        # 目前返回模拟结果
        return {
            "success": True,
            "improvement": 0.15,  # 模拟15%改进
            "message": "Suggestion applied successfully",
        }

    def _calculate_quality_score(self, suggestion: Dict, improvement: float) -> float:
        """计算建议质量分数"""
        score = improvement * 100

        # 验证通过加成
        if suggestion.get("verified"):
            score *= 1.2

        # 重复验证加成
        verify_count = suggestion.get("verify_count", 0)
        if verify_count > 0:
            score *= 1 + 0.1 * verify_count

        return min(100.0, score)

    def _record_feedback(self, feedback: Dict):
        """记录反馈"""
        feedback_file = WORKSPACE / "state" / "feedback_loop.json"

        if feedback_file.exists():
            try:
                data = json.loads(feedback_file.read_text(encoding="utf-8"))
            except Exception:
                data = {"feedbacks": []}
        else:
            data = {"feedbacks": []}

        feedback["timestamp"] = datetime.now().isoformat()
        data["feedbacks"].append(feedback)

        feedback_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _on_failure_tracked(self, operation: Dict, outcome: Dict):
        """失败追踪时触发学习"""
        # 导入学习核心
        from .learning_core import get_learning_core

        learning_core = get_learning_core()

        # 构建失败信息
        failure = {
            "tool": operation.get("tool"),
            "action": operation.get("action"),
            "error_type": outcome.get("error_type", "unknown"),
            "error_message": outcome.get("error_message", ""),
            "timestamp": datetime.now().isoformat(),
        }

        # 触发学习
        learning_core.on_failure(failure)


# 全局实例
_outcome_tracker = None


def get_outcome_tracker() -> OutcomeTracker:
    """获取全局效果追踪器实例"""
    global _outcome_tracker
    if _outcome_tracker is None:
        _outcome_tracker = OutcomeTracker()
    return _outcome_tracker


if __name__ == "__main__":
    # 测试
    tracker = OutcomeTracker()

    # 测试创建建议
    suggestion = {
        "type": "optimization",
        "content": "优化记忆写入性能",
        "domain": "memory",
    }
    suggestion_id = tracker.create_suggestion(suggestion)
    print(f"✅ 创建建议: {suggestion_id}")

    # 测试应用建议
    result = tracker.apply_suggestion(suggestion_id)
    print(f"✅ 应用结果: {result}")

    # 测试验证建议
    result = tracker.verify_suggestion(suggestion_id, 0.15)
    print(f"✅ 验证结果: {result}")

    # 测试统计
    stats = tracker.get_outcome_stats()
    print(f"✅ 统计: {stats}")
