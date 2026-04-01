#!/usr/bin/env python3
"""
learning_core.py - 统一学习系统核心
合并12个学习工具，提供统一的学习功能

特性：
- 统一接口：一个模块处理所有学习相关操作
- 自动触发：失败、成功、异常自动触发学习
- 低Token消耗：懒加载 + 缓存 + 智能触发
- 全自动闭环：无需人工干预
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from collections import defaultdict

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.state_manager import get_state_manager

WORKSPACE = Path(
    os.environ.get("OPENCLAW_WORKSPACE", Path(__file__).parent.parent.parent)
)
STATE_DIR = WORKSPACE / "state"
LEARNINGS_DIR = WORKSPACE / ".learnings"


class LearningCore:
    """统一学习系统核心"""

    def __init__(self):
        self.state = get_state_manager()
        self._solution_cache = {}
        self._cache_ttl = 300  # 5分钟缓存

    # ============================================================
    # 核心学习功能
    # ============================================================

    def on_failure(self, failure: Dict) -> Dict:
        """
        失败发生时自动触发学习
        自动判断是否需要分析，避免重复分析
        """
        # 检查是否应该触发分析
        if not self._should_analyze(failure):
            return {"analyzed": False, "reason": "low_priority"}

        # 查找现有解决方案
        existing = self._find_existing_solution(failure)
        if existing:
            return {"analyzed": True, "found_existing": True, "solution": existing}

        # 记录失败，等待LLM分析
        self._record_failure_for_analysis(failure)
        return {"analyzed": True, "queued_for_analysis": True}

    def on_success(self, operation: Dict) -> Dict:
        """
        成功操作时自动学习
        提取成功模式，加入解决方案库
        """
        # 提取成功特征
        features = self._extract_success_features(operation)

        # 加入解决方案库
        self._add_to_solution_library(
            {
                "type": "success",
                "features": features,
                "operation": operation,
                "timestamp": datetime.now().isoformat(),
                "verified": True,
            }
        )

        return {"learned": True, "features_count": len(features)}

    def on_anomaly(self, anomaly: Dict) -> Dict:
        """
        检测到异常时自动学习
        分析异常模式，预测潜在问题
        """
        # 判断异常是否值得分析
        if not self._is_worth_analyzing(anomaly):
            return {"analyzed": False, "reason": "low_severity"}

        # 分析异常模式
        patterns = self._analyze_anomaly_patterns(anomaly)

        # 记录异常
        self._record_anomaly(anomaly, patterns)

        return {"analyzed": True, "patterns": patterns}

    def on_file_changed(self, file_path: str) -> Dict:
        """
        文件变更时自动触发学习
        用于.learnings/目录变更时自动更新知识
        """
        path = Path(file_path)

        # 只处理.learnings/目录下的.md文件
        if ".learnings" not in str(path) or not path.suffix == ".md":
            return {"processed": False, "reason": "not_learning_file"}

        # 读取文件内容
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            return {"processed": False, "error": str(e)}

        # 提取知识点
        insights = self._extract_insights(content, str(path))

        # 更新知识地图
        if insights:
            self._update_knowledge_map(insights, str(path))

        return {"processed": True, "insights_count": len(insights)}

    # ============================================================
    # 解决方案管理
    # ============================================================

    def find_solution(self, problem: Dict) -> Optional[Dict]:
        """查找问题的解决方案"""
        # 检查缓存
        cache_key = self._make_cache_key(problem)
        if cache_key in self._solution_cache:
            cached_solution, cached_time = self._solution_cache[cache_key]
            if (datetime.now() - cached_time).seconds < self._cache_ttl:
                return cached_solution

        # 精确匹配
        exact_match = self._find_exact_match(problem)
        if exact_match:
            self._solution_cache[cache_key] = (exact_match, datetime.now())
            return exact_match

        # 同类错误匹配
        similar_match = self._find_similar_match(problem)
        if similar_match:
            self._solution_cache[cache_key] = (similar_match, datetime.now())
            return similar_match

        # 高频解决方案推荐
        high_freq = self._get_high_frequency_solutions()
        if high_freq:
            self._solution_cache[cache_key] = (high_freq[0], datetime.now())
            return high_freq[0]

        return None

    def _find_exact_match(self, problem: Dict) -> Optional[Dict]:
        """精确匹配解决方案"""
        solutions = self.state.get("learning.crystallized_knowledge", [])

        for solution in solutions:
            if solution.get("type") == "exact_match":
                if self._matches_problem(solution, problem):
                    return solution
        return None

    def _find_similar_match(self, problem: Dict) -> Optional[Dict]:
        """同类错误匹配"""
        solutions = self.state.get("learning.crystallized_knowledge", [])

        problem_type = problem.get("error_type") or problem.get("type")
        if not problem_type:
            return None

        for solution in solutions:
            if solution.get("problem_type") == problem_type:
                return solution
        return None

    def _get_high_frequency_solutions(self) -> List[Dict]:
        """获取高频解决方案"""
        solutions = self.state.get("learning.crystallized_knowledge", [])

        # 按验证次数排序
        verified_solutions = [
            s
            for s in solutions
            if s.get("verified", False) and s.get("verified_count", 0) > 0
        ]

        return sorted(
            verified_solutions, key=lambda x: x.get("verified_count", 0), reverse=True
        )[:5]

    def _add_to_solution_library(self, solution: Dict):
        """添加解决方案到库"""
        solutions = self.state.get("learning.crystallized_knowledge", [])

        # 检查是否已存在
        existing_idx = None
        for i, s in enumerate(solutions):
            if self._solutions_match(s, solution):
                existing_idx = i
                break

        if existing_idx is not None:
            # 更新现有解决方案
            solutions[existing_idx]["verified_count"] = (
                solutions[existing_idx].get("verified_count", 0) + 1
            )
            solutions[existing_idx]["last_verified"] = datetime.now().isoformat()
        else:
            # 添加新解决方案
            solution["verified_count"] = 1
            solution["created"] = datetime.now().isoformat()
            solutions.append(solution)

        # 限制数量，保留最新的100个
        if len(solutions) > 100:
            solutions = solutions[-100:]

        self.state.set("learning.crystallized_knowledge", solutions)

    # ============================================================
    # 知识地图管理（含时间衰减）
    # ============================================================

    # 时间衰减参数
    DECAY_INTERVAL_DAYS = 30
    DECAY_AMOUNT = 0.05
    MIN_CONFIDENCE = 0.1

    def _update_knowledge_map(self, insights: List[Dict], source_file: str):
        """更新知识地图（含时间衰减）"""
        km = self.state.get("learning.knowledge_map", {})
        now = datetime.now()

        # 先对所有领域应用时间衰减
        for domain, info in km.items():
            last_updated = info.get("last_updated")
            if last_updated:
                try:
                    last_dt = datetime.fromisoformat(last_updated)
                    days_idle = (now - last_dt).days
                    if days_idle >= self.DECAY_INTERVAL_DAYS:
                        periods = days_idle // self.DECAY_INTERVAL_DAYS
                        decay = periods * self.DECAY_AMOUNT
                        new_conf = max(
                            self.MIN_CONFIDENCE, info.get("confidence", 0.5) - decay
                        )
                        info["confidence"] = round(new_conf, 2)
                except Exception:
                    pass

        for insight in insights:
            domain = insight.get("domain", "general")

            if domain not in km:
                km[domain] = {
                    "confidence": 0.5,
                    "experience_count": 0,
                    "last_updated": None,
                    "sources": [],
                }

            # 更新领域信息
            km[domain]["experience_count"] += 1
            km[domain]["last_updated"] = datetime.now().isoformat()

            # 置信度增长（每次经验 +0.05，最高0.95）
            km[domain]["confidence"] = min(0.95, km[domain]["confidence"] + 0.05)

            # 记录来源（最多保留10个）
            if source_file not in km[domain]["sources"]:
                km[domain]["sources"].append(source_file)
                if len(km[domain]["sources"]) > 10:
                    km[domain]["sources"] = km[domain]["sources"][-10:]

        self.state.set("learning.knowledge_map", km)

    def get_domain_confidence(self, domain: str) -> float:
        """获取领域置信度"""
        km = self.state.get("learning.knowledge_map", {})
        return km.get(domain, {}).get("confidence", 0.0)

    def get_weak_domains(self, threshold: float = 0.3) -> List[tuple]:
        """获取低置信度领域"""
        km = self.state.get("learning.knowledge_map", {})
        weak = []
        for domain, info in km.items():
            if info.get("confidence", 0) < threshold:
                weak.append((domain, info.get("confidence", 0)))
        return sorted(weak, key=lambda x: x[1])

    # ============================================================
    # 智能触发判断
    # ============================================================

    def _should_analyze(self, failure: Dict) -> bool:
        """判断是否应该分析失败"""
        # 计算优先级分数
        score = self._calculate_priority_score(failure)

        # 阈值：50分
        return score >= 50

    def _calculate_priority_score(self, failure: Dict) -> int:
        """计算失败的优先级分数"""
        score = 0

        # 重复失败 +50分
        if self._is_repeated_failure(failure):
            score += 50

        # 高影响 +30分
        if failure.get("impact") == "high":
            score += 30

        # 未知根因 +20分
        if not failure.get("root_cause"):
            score += 20

        # 最近发生 +10分
        if self._is_recent(failure):
            score += 10

        return score

    def _is_repeated_failure(self, failure: Dict) -> bool:
        """检查是否是重复失败"""
        failures = self.state.get("system.failures", [])

        # 检查最近7天内是否有相同类型的失败
        cutoff = (datetime.now() - timedelta(days=7)).isoformat()

        for f in failures:
            if f.get("timestamp", "") > cutoff:
                if f.get("tool") == failure.get("tool") and f.get(
                    "error_type"
                ) == failure.get("error_type"):
                    return True

        return False

    def _is_recent(self, failure: Dict, days: int = 7) -> bool:
        """检查是否是最近发生的"""
        if not failure.get("timestamp"):
            return True  # 没有时间戳视为最近

        failure_time = datetime.fromisoformat(failure["timestamp"])
        cutoff = datetime.now() - timedelta(days=days)

        return failure_time > cutoff

    def _is_worth_analyzing(self, anomaly: Dict) -> bool:
        """判断异常是否值得分析"""
        # 错误率>20% 或 活动量<30% 值得分析
        error_rate = anomaly.get("error_rate", 0)
        activity_rate = anomaly.get("activity_rate", 100)

        return error_rate > 20 or activity_rate < 30

    # ============================================================
    # 失败记录与分析
    # ============================================================

    def _record_failure_for_analysis(self, failure: Dict):
        """记录失败，等待分析"""
        failures = self.state.get("system.failures", [])

        # 添加时间戳
        failure["timestamp"] = datetime.now().isoformat()
        failure["analyzed"] = False

        failures.append(failure)

        # 限制数量，保留最近500个
        if len(failures) > 500:
            failures = failures[-500:]

        self.state.set("system.failures", failures)

    def _record_anomaly(self, anomaly: Dict, patterns: List[Dict]):
        """记录异常"""
        anomalies = self.state.get("system.anomalies", [])

        anomaly["timestamp"] = datetime.now().isoformat()
        anomaly["patterns"] = patterns

        anomalies.append(anomaly)

        # 限制数量，保留最近100个
        if len(anomalies) > 100:
            anomalies = anomalies[-100:]

        self.state.set("system.anomalies", anomalies)

    # ============================================================
    # 洞察提取
    # ============================================================

    def _extract_insights(self, content: str, source_file: str) -> List[Dict]:
        """从内容中提取知识点"""
        insights = []

        # 关键词映射到领域
        domain_keywords = {
            "Python开发": ["python", "pip", "虚拟环境", "装饰器", "生成器"],
            "系统架构": ["架构", "设计模式", "微服务", "API", "接口"],
            "前端开发": ["react", "vue", "javascript", "css", "html", "前端"],
            "数据库": ["数据库", "sql", "mysql", "postgresql", "查询优化"],
            "DevOps": ["docker", "kubernetes", "ci/cd", "部署", "运维"],
            "测试": ["测试", "单元测试", "集成测试", "pytest", "jest"],
            "文档撰写": ["文档", "markdown", "readme", "注释"],
            "调试": ["bug", "调试", "错误", "异常", "修复"],
            "飞书/Lark": ["飞书", "lark", "feishu", "飞书开放平台", "webhook"],
            "群聊行为": ["群聊", "chat_id", "oc_", "群成员", "私聊", "DM"],
            "隐私保护": ["ou_id", "ou_", "隐私", "泄露", "敏感", "个人信息"],
            "Word处理": ["word", "docx", "openxml", "minimax-docx"],
            "Excel处理": ["excel", "xlsx", "openpyxl", "spreadsheet"],
            "技能管理": ["skill", "skills", "技能", "find-skills", "安装"],
            "AI模型": [
                "model",
                "nvidia",
                "step",
                "multimodal",
                "幻觉",
                "hallucination",
            ],
            "自动化/Cron": ["cron", "crontab", "scheduled", "定时", "heartbeat"],
            "搜索": ["tavily", "web_search", "搜索", "perplexity", "检索"],
        }

        content_lower = content.lower()

        for domain, keywords in domain_keywords.items():
            matches = [kw for kw in keywords if kw.lower() in content_lower]
            if matches:
                insights.append(
                    {
                        "domain": domain,
                        "keywords": matches,
                        "source": source_file,
                        "timestamp": datetime.now().isoformat(),
                    }
                )

        return insights

    def _extract_success_features(self, operation: Dict) -> List[str]:
        """提取成功特征"""
        features = []

        # 提取工具名称
        if operation.get("tool"):
            features.append(f"tool:{operation['tool']}")

        # 提取操作类型
        if operation.get("action"):
            features.append(f"action:{operation['action']}")

        # 提取参数特征
        params = operation.get("params", {})
        for key, value in params.items():
            if isinstance(value, str) and len(value) < 50:
                features.append(f"param:{key}={value}")

        return features

    def _analyze_anomaly_patterns(self, anomaly: Dict) -> List[Dict]:
        """分析异常模式"""
        patterns = []

        # 分析错误率模式
        if anomaly.get("error_rate", 0) > 20:
            patterns.append(
                {
                    "type": "high_error_rate",
                    "value": anomaly["error_rate"],
                    "threshold": 20,
                }
            )

        # 分析活动量模式
        if anomaly.get("activity_rate", 100) < 30:
            patterns.append(
                {
                    "type": "low_activity",
                    "value": anomaly["activity_rate"],
                    "threshold": 30,
                }
            )

        return patterns

    # ============================================================
    # 辅助函数
    # ============================================================

    def _make_cache_key(self, problem: Dict) -> str:
        """生成缓存键"""
        key_parts = []
        for k in ["tool", "error_type", "action"]:
            if k in problem:
                key_parts.append(f"{k}:{problem[k]}")
        return "|".join(key_parts)

    def _matches_problem(self, solution: Dict, problem: Dict) -> bool:
        """检查解决方案是否匹配问题"""
        # 检查工具匹配
        if solution.get("tool") and solution["tool"] != problem.get("tool"):
            return False

        # 检查错误类型匹配
        if solution.get("error_type") and solution["error_type"] != problem.get(
            "error_type"
        ):
            return False

        # 检查操作匹配
        if solution.get("action") and solution["action"] != problem.get("action"):
            return False

        return True

    def _solutions_match(self, s1: Dict, s2: Dict) -> bool:
        """检查两个解决方案是否相同"""
        return (
            s1.get("tool") == s2.get("tool")
            and s1.get("error_type") == s2.get("error_type")
            and s1.get("action") == s2.get("action")
        )

    # ============================================================
    # 学习 ROI 度量（宽松阈值）
    # ============================================================

    def calculate_learning_roi(self) -> Dict:
        """
        计算学习 ROI：每条规则/方案的成功率。
        宽松阈值：success_rate > 0.05 即视为有效（聊天较少时不触发很正常）。
        """
        solutions = self.state.get("learning.crystallized_knowledge", [])
        failures = self.state.get("system.failures", [])

        if not solutions and not failures:
            return {"total_solutions": 0, "total_failures": 0, "roi": "N/A"}

        # 统计每个方案的使用情况
        solution_stats = {}
        for s in solutions:
            key = f"{s.get('tool', 'unknown')}:{s.get('error_type', 'unknown')}"
            solution_stats[key] = {
                "verified_count": s.get("verified_count", 0),
                "created": s.get("created", ""),
            }

        # 统计失败次数（按 tool:error_type 分组）
        failure_counts = defaultdict(int)
        for f in failures:
            key = f"{f.get('tool', 'unknown')}:{f.get('error_type', 'unknown')}"
            failure_counts[key] += 1

        # 计算 ROI
        roi_results = []
        for key, stats in solution_stats.items():
            successes = stats["verified_count"]
            total_attempts = successes + failure_counts.get(key, 0)
            if total_attempts > 0:
                success_rate = successes / total_attempts
            else:
                success_rate = 0.0
            roi_results.append(
                {
                    "key": key,
                    "successes": successes,
                    "failures": failure_counts.get(key, 0),
                    "success_rate": round(success_rate, 3),
                    "effective": success_rate > 0.05,  # 宽松阈值
                }
            )

        # 过滤掉无效的（success_rate <= 0.05 且有失败记录的）
        ineffective = [
            r for r in roi_results if not r["effective"] and r["failures"] > 0
        ]

        return {
            "total_solutions": len(solutions),
            "total_failures": len(failures),
            "roi_details": roi_results,
            "ineffective_count": len(ineffective),
            "threshold": 0.05,
        }


# 全局实例
_learning_core = None


def get_learning_core() -> LearningCore:
    """获取全局学习核心实例"""
    global _learning_core
    if _learning_core is None:
        _learning_core = LearningCore()
    return _learning_core


# ============================================================
# 钩子函数（供其他模块调用）
# ============================================================


def on_failure(failure: Dict) -> Dict:
    """失败钩子"""
    return get_learning_core().on_failure(failure)


def on_success(operation: Dict) -> Dict:
    """成功钩子"""
    return get_learning_core().on_success(operation)


def on_anomaly(anomaly: Dict) -> Dict:
    """异常钩子"""
    return get_learning_core().on_anomaly(anomaly)


def on_file_changed(file_path: str) -> Dict:
    """文件变更钩子"""
    return get_learning_core().on_file_changed(file_path)


def find_solution(problem: Dict) -> Optional[Dict]:
    """查找解决方案"""
    return get_learning_core().find_solution(problem)


if __name__ == "__main__":
    # 测试
    core = LearningCore()

    # 测试失败学习
    failure = {
        "tool": "write_memory",
        "error_type": "permission_denied",
        "message": "无法写入文件",
    }
    result = core.on_failure(failure)
    print(f"✅ 失败学习: {result}")

    # 测试成功学习
    operation = {"tool": "evolve_rules", "action": "evolve", "params": {"days": 7}}
    result = core.on_success(operation)
    print(f"✅ 成功学习: {result}")

    # 测试知识地图
    confidence = core.get_domain_confidence("Python开发")
    print(f"✅ Python开发置信度: {confidence}")
