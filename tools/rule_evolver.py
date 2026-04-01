#!/usr/bin/env python3
"""
rule_evolver.py - 规则演化系统
合并evolve_rules、prune_rules、promote_critical_rules

特性：
- 每日自动学习提炼
- 从.learnings/中蒸馏行为规则
- 规则清理与提升
- 全自动运行
"""

import json
import os
import sys
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.state_manager import get_state_manager

WORKSPACE = Path(
    os.environ.get("OPENCLAW_WORKSPACE", Path(__file__).parent.parent.parent)
)
STATE_DIR = WORKSPACE / "state"
LEARNINGS_DIR = WORKSPACE / ".learnings"

# 规则文件
AUTO_RULES_FILE = STATE_DIR / "auto_learned_rules.md"
AUTO_RULES_HOT_FILE = STATE_DIR / "auto_learned_rules_hot.md"
AUTO_RULES_COLD_FILE = STATE_DIR / "auto_learned_rules_cold.md"
SYSTEM_CONTEXT = WORKSPACE / "SYSTEM-CONTEXT.md"

# 关键规则定义
CRITICAL_RULES = {
    "rule_tavily_search": {
        "title": "⚠️ 搜索工具",
        "rule": "必须使用 tools/tavily_search.py，禁止使用 web_search",
    },
    "rule_feishu_tools": {
        "title": "⚠️ 飞书操作",
        "rule": "必须使用 feishu_* 系列工具（openclaw-lark 插件）",
    },
    "rule_memory_append_only": {
        "title": "⚠️ memory 文件保护",
        "rule": "memory/YYYY-MM-DD.md 只追加，禁止 Write/Edit 覆盖",
    },
    "rule_group_chat_routing": {
        "title": "⚠️ 群聊内容路由",
        "rule": "群聊内容必须用 group-daily，禁止写入 memory/",
    },
}


class RuleEvolver:
    """规则演化系统"""

    def __init__(self):
        self.state = get_state_manager()

    def evolve(self, days: int = 7):
        """
        每日规则演化
        从.learnings/中提取洞察，生成规则
        """
        print(f"🔄 开始规则演化（扫描最近 {days} 天）...")

        # 扫描learnings
        insights = self._scan_learnings(days)

        # 提取规则
        rules = self._extract_rules(insights)

        # 分类规则
        hot_rules, cold_rules = self._classify_rules(rules)

        # 保存规则
        self._save_rules(hot_rules, cold_rules)

        # 更新状态
        self.state.append(
            "rules.evolution_log",
            {
                "timestamp": datetime.now().isoformat(),
                "days_scanned": days,
                "insights_count": len(insights),
                "rules_extracted": len(rules),
                "hot_rules": len(hot_rules),
                "cold_rules": len(cold_rules),
            },
            max_items=100,
        )

        print(
            f"✅ 规则演化完成: {len(rules)} 条规则（{len(hot_rules)} 热, {len(cold_rules)} 冷）"
        )

        return {
            "insights": len(insights),
            "rules": len(rules),
            "hot": len(hot_rules),
            "cold": len(cold_rules),
        }

    def _scan_learnings(self, days: int) -> List[Dict]:
        """扫描learnings目录"""
        insights = []
        cutoff = datetime.now() - timedelta(days=days)

        for file_path in LEARNINGS_DIR.glob("*.md"):
            if file_path.name in ["LEARNINGS.md", "index.json"]:
                continue

            # 检查文件修改时间
            mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
            if mtime < cutoff:
                continue

            try:
                content = file_path.read_text(encoding="utf-8")

                # 提取洞察
                file_insights = self._extract_insights_from_content(
                    content, file_path.name
                )
                insights.extend(file_insights)

            except Exception as e:
                print(f"⚠️ 读取 {file_path.name} 失败: {e}")

        return insights

    def _extract_insights_from_content(self, content: str, filename: str) -> List[Dict]:
        """从内容中提取洞察"""
        insights = []

        # 触发提炼的信号词
        insight_signals = [
            "踩坑",
            "注意",
            "应该",
            "不应该",
            "教训",
            "经验",
            "问题",
            "解决",
            "方案",
            "优化",
            "改进",
            "避免",
        ]

        lines = content.split("\n")
        for i, line in enumerate(lines):
            line_lower = line.lower()

            # 检查是否包含信号词
            if any(signal in line_lower for signal in insight_signals):
                # 提取上下文（前后各2行）
                start = max(0, i - 2)
                end = min(len(lines), i + 3)
                context = "\n".join(lines[start:end])

                insights.append(
                    {
                        "source": filename,
                        "line": i + 1,
                        "content": line.strip(),
                        "context": context,
                        "timestamp": datetime.now().isoformat(),
                    }
                )

        return insights

    def _extract_rules(self, insights: List[Dict]) -> List[Dict]:
        """从洞察中提取规则"""
        rules = []

        for insight in insights:
            content = insight["content"]

            # 简单的规则提取逻辑
            if "应该" in content or "必须" in content or "禁止" in content:
                rule = {
                    "id": f"rule_{insight['source']}_{insight['line']}",
                    "content": content,
                    "source": insight["source"],
                    "type": "behavior",
                    "confidence": 0.7,
                    "created": datetime.now().isoformat(),
                }
                rules.append(rule)

            elif "避免" in content or "不要" in content:
                rule = {
                    "id": f"rule_{insight['source']}_{insight['line']}",
                    "content": content,
                    "source": insight["source"],
                    "type": "avoidance",
                    "confidence": 0.6,
                    "created": datetime.now().isoformat(),
                }
                rules.append(rule)

        return rules

    def _classify_rules(self, rules: List[Dict]) -> tuple:
        """分类规则为热规则和冷规则"""
        hot_rules = []
        cold_rules = []

        # 获取规则元数据
        metadata = self.state.get("rules.metadata", {})

        for rule in rules:
            rule_id = rule["id"]

            # 检查是否是高频触发的规则
            if rule_id in metadata:
                meta = metadata[rule_id]
                trigger_count = meta.get("trigger_count", 0)

                if trigger_count >= 3:
                    # 高频触发，归为热规则
                    rule["confidence"] = min(0.95, rule["confidence"] + 0.1)
                    hot_rules.append(rule)
                else:
                    cold_rules.append(rule)
            else:
                # 新规则，默认为冷规则
                cold_rules.append(rule)

        return hot_rules, cold_rules

    def _save_rules(self, hot_rules: List[Dict], cold_rules: List[Dict]):
        """保存规则"""
        # 保存热规则
        hot_content = self._format_rules(hot_rules, "热规则（高频触发）")
        AUTO_RULES_HOT_FILE.write_text(hot_content, encoding="utf-8")

        # 保存冷规则
        cold_content = self._format_rules(cold_rules, "冷规则（低频/新规则）")
        AUTO_RULES_COLD_FILE.write_text(cold_content, encoding="utf-8")

        # 保存合并规则
        all_rules = hot_rules + cold_rules
        all_content = self._format_rules(all_rules, "自动生成规则")
        AUTO_RULES_FILE.write_text(all_content, encoding="utf-8")

        # 更新状态
        self.state.set(
            "rules.auto_learned",
            {
                "hot": [r["id"] for r in hot_rules],
                "cold": [r["id"] for r in cold_rules],
                "last_updated": datetime.now().isoformat(),
            },
        )

    def _format_rules(self, rules: List[Dict], title: str) -> str:
        """格式化规则"""
        lines = [
            f"# {title}",
            f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]

        if not rules:
            lines.append("暂无规则")
            return "\n".join(lines)

        # 按类型分组
        by_type = {}
        for rule in rules:
            rule_type = rule.get("type", "other")
            if rule_type not in by_type:
                by_type[rule_type] = []
            by_type[rule_type].append(rule)

        for rule_type, type_rules in by_type.items():
            lines.append(f"## {rule_type}")
            lines.append("")

            for rule in type_rules:
                lines.append(f"- **{rule['id']}**: {rule['content']}")

            lines.append("")

        return "\n".join(lines)

    def prune(self, days: int = 90):
        """
        清理长期未触发的规则
        """
        print(f"🧹 开始清理规则（{days} 天未触发）...")

        metadata = self.state.get("rules.metadata", {})
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        to_remove = []
        for rule_id, meta in metadata.items():
            last_triggered = meta.get("last_triggered", "")
            trigger_count = meta.get("trigger_count", 0)

            # 清理条件：超过N天未触发 或 触发次数为0
            if (last_triggered and last_triggered < cutoff) or trigger_count == 0:
                to_remove.append(rule_id)

        # 删除规则
        for rule_id in to_remove:
            del metadata[rule_id]

        self.state.set("rules.metadata", metadata)

        print(f"✅ 清理完成: 删除 {len(to_remove)} 条规则")
        return {"removed": len(to_remove)}

    def promote_critical(self):
        """
        将高频违规规则提升到显眼位置
        """
        print("⬆️ 提升高频违规规则...")

        # 获取高频违规
        violations = self.state.get("rules.violations", [])
        high_freq = self._get_high_frequency_violations(violations)

        if not high_freq:
            print("✅ 无高频违规规则")
            return {"promoted": 0}

        # 提升到 SYSTEM-CONTEXT.md
        self._promote_to_system_context(high_freq)

        print(f"✅ 提升完成: {len(high_freq)} 条规则")
        return {"promoted": len(high_freq)}

    def _get_high_frequency_violations(
        self, violations: List[Dict], threshold: int = 3
    ) -> List[str]:
        """获取高频违规规则"""
        counts = {}
        for v in violations:
            rule_id = v.get("rule_id")
            if rule_id:
                counts[rule_id] = counts.get(rule_id, 0) + 1

        return [rule_id for rule_id, count in counts.items() if count >= threshold]

    def _promote_to_system_context(self, rule_ids: List[str]):
        """提升规则到 SYSTEM-CONTEXT.md"""
        # 构建高频规则部分
        lines = [
            "# ⚠️ 高频错误规则（自动生成）",
            f"> 更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "> 这些规则违规频率高，必须严格遵守",
            "",
        ]

        for rule_id in rule_ids:
            if rule_id in CRITICAL_RULES:
                rule = CRITICAL_RULES[rule_id]
                lines.append(f"## {rule['title']}")
                lines.append(f"**{rule['rule']}**")
                lines.append("")

        lines.append("---\n")

        # 读取现有内容
        if SYSTEM_CONTEXT.exists():
            existing = SYSTEM_CONTEXT.read_text(encoding="utf-8")
            # 移除旧的高频规则部分
            if "# ⚠️ 高频错误规则" in existing:
                parts = existing.split("---\n", 1)
                existing = parts[1] if len(parts) > 1 else existing
        else:
            existing = ""

        # 写入新内容
        new_content = "\n".join(lines) + existing
        SYSTEM_CONTEXT.write_text(new_content, encoding="utf-8")


# 全局实例
_rule_evolver = None


def get_rule_evolver() -> RuleEvolver:
    """获取全局规则演化器实例"""
    global _rule_evolver
    if _rule_evolver is None:
        _rule_evolver = RuleEvolver()
    return _rule_evolver


if __name__ == "__main__":
    # 测试
    evolver = RuleEvolver()

    # 测试演化
    result = evolver.evolve(days=7)
    print(f"✅ 演化结果: {result}")

    # 测试清理
    result = evolver.prune(days=90)
    print(f"✅ 清理结果: {result}")

    # 测试提升
    result = evolver.promote_critical()
    print(f"✅ 提升结果: {result}")
