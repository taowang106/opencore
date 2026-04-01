#!/usr/bin/env python3
"""
evolve_rules - 每日自动学习提炼，从 .learnings/ 中蒸馏行为规则
存在即学习：无阈值筛选，扫描到的洞察直接固化
直接执行，无需人工审核

输出：
  - state/auto_learned_rules.md  → 最新规则快照（可被 core_loader 加载）
  - state/auto_learned_rules_hot.md  → 热规则（高频触发、高置信度）
  - state/auto_learned_rules_cold.md → 冷规则（低频/新规则，归档参考）
  - state/evolution_log.json     → 进化历史追踪
  - .learnings/YYYY-MM-DD-进化摘要.md → 本次提炼记录

用法：
  python3 tools/evolve_rules.py           # 默认扫描最近7天
  python3 tools/evolve_rules.py --all     # 扫描全部 learnings
  python3 tools/evolve_rules.py --days 3  # 扫描最近3天
"""

import json
import os
import re
import sys
import math
import hashlib
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

# 行为日志系统
try:
    from operation_logger import log_operation
except ImportError:

    def log_operation(*args, **kwargs):
        pass


# 规则元数据追踪
try:
    from rules_metadata import (
        register_rule,
        load_metadata,
        get_stale_rules,
        get_effective_weight,
    )
except ImportError:

    def register_rule(rule_id, source="auto", initial_confidence=0.7):
        pass

    def load_metadata():
        return {}

    def get_stale_rules(days=90):
        return []

    def get_effective_weight(rule_id):
        return 0.5


# 知识地图更新
try:
    from knowledge_map import update_from_learning
except ImportError:

    def update_from_learning(content, source_file):
        print("  ⚠️ knowledge_map 模块不可用，跳过知识地图更新")


WORKSPACE = Path(os.environ.get("OPENCLAW_WORKSPACE", Path(__file__).parent.parent))
STATE_DIR = WORKSPACE / "state"
LEARNINGS_DIR = WORKSPACE / ".learnings"
AUTO_RULES_FILE = STATE_DIR / "auto_learned_rules.md"
AUTO_RULES_HOT_FILE = STATE_DIR / "auto_learned_rules_hot.md"
AUTO_RULES_COLD_FILE = STATE_DIR / "auto_learned_rules_cold.md"
EVOLUTION_LOG_FILE = STATE_DIR / "evolution_log.json"
PENDING_REVIEW_FILE = STATE_DIR / "rules_pending_review.md"

# auto_learned_rules.md 最大行数：超出后只保留各主题第一条
MAX_RULES_LINES = 300

# 排除的 topic（文件名中包含这些词的不参与提炼）
EXCLUDE_TOPICS = {"进化摘要", "自动观察", "测试主题", "测试"}

# 低质量文件特征：包含这些标记的文件跳过提炼
LOW_QUALITY_MARKERS = [
    "自动观察日志",
    "write_memory.daily 成功",
    "evolve_rules.evolve 成功",
    "测试learning",
    "测试洞察",
]

# 触发提炼的信号词
INSIGHT_SIGNALS = [
    "踩坑",
    "注意",
    "应该",
    "不应该",
    "规则",
    "原则",
    "避免",
    "必须",
    "禁止",
    "最佳实践",
    "经验",
    "教训",
    "发现",
    "改进",
    "优化",
    "要点",
    "关键",
    "下次",
    "以后",
    "记住",
    "重要",
    "坑",
    "失败",
    "成功",
    "有效",
    "无效",
    "MUST",
    "NEVER",
    "ALWAYS",
    "NOTE",
    "WARNING",
    "TIP",
]

# 日期前缀的正则（用于解析 .learnings/ 文件名）
DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)\.md$")


# ── 热冷分离阈值 ──────────────────────────────────────────────────────────
HOT_CONFIDENCE_THRESHOLD = 0.5  # 置信度 >= 此值为热规则（V3.4.0: 从0.6降至0.5）
HOT_TRIGGER_MIN = 3  # 触发次数 >= 此值为热规则
COLD_STALE_DAYS = 90  # 超过此天数未触发标记为冷规则
NEW_RULE_PROTECTION_DAYS = 7  # 7天内新创建的规则即使触发为0也进入热规则


def load_evolution_log() -> dict:
    if EVOLUTION_LOG_FILE.exists():
        try:
            return json.loads(EVOLUTION_LOG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "events": [],
        "rules_version": 0,
        "total_learnings_processed": 0,
        "last_insights_hash": "",
    }


def save_evolution_log(log: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = EVOLUTION_LOG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(log, ensure_ascii=False, indent=2))
    os.replace(tmp, EVOLUTION_LOG_FILE)

    # 同步到 unified_state.json（上限200条）
    try:
        unified_file = STATE_DIR / "unified_state.json"
        if unified_file.exists():
            state = json.loads(unified_file.read_text(encoding="utf-8"))
            events = log.get("events", [])
            state.setdefault("rules", {})["evolution_log"] = (
                events[-200:] if len(events) > 200 else events
            )
            tmp2 = unified_file.with_suffix(".tmp2")
            tmp2.write_text(
                json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(tmp2, unified_file)
    except Exception:
        pass  # 同步失败不影响主流程


def collect_permanent_learning_files() -> list:
    if not LEARNINGS_DIR.exists():
        return []
    files = []
    for f in sorted(LEARNINGS_DIR.glob("*.md")):
        if DATE_PREFIX_RE.match(f.name):
            continue
        topic = f.stem
        if topic in EXCLUDE_TOPICS:
            continue
        files.append({"path": f, "date": datetime.min, "topic": topic})
    return files


def collect_learning_files(days: int = 7, all_files: bool = False) -> list:
    if not LEARNINGS_DIR.exists():
        return []
    cutoff = datetime.now() - timedelta(days=days)
    files = []
    for f in sorted(LEARNINGS_DIR.glob("*.md")):
        m = DATE_PREFIX_RE.match(f.name)
        if not m:
            continue
        try:
            file_date = datetime.strptime(m.group(1), "%Y-%m-%d")
        except ValueError:
            continue
        topic = m.group(2)
        if topic in EXCLUDE_TOPICS:
            continue
        # 文件名级别过滤：排除含"测试"、"自动观察"的文件
        if "测试" in topic or "自动观察" in topic or "test" in topic.lower():
            continue
        if all_files or file_date >= cutoff:
            files.append({"path": f, "date": file_date, "topic": topic})
    return files


def extract_insights_from_file(filepath: Path) -> list:
    insights = []
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception:
        return insights

    # 新增：质量评分过滤
    try:
        from learning_quality_scorer import score_learning

        score_result = score_learning(content, filepath.name)

        if not score_result["should_learn"]:
            print(
                f"  跳过低质量文件: {filepath.name} (分数: {score_result['score']}, 原因: {', '.join(score_result['reasons'])})"
            )
            return insights
        else:
            print(
                f"  ✓ 质量检查通过: {filepath.name} (分数: {score_result['score']}, 质量: {score_result['quality']})"
            )
    except Exception as e:
        print(f"  ⚠️ 质量评分失败: {e}，继续处理")

    if "已废弃" in content or "DEPRECATED" in content.upper():
        return insights
    if any(marker in content for marker in LOW_QUALITY_MARKERS):
        return insights

    lines = content.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        if not line or line.startswith("#"):
            i += 1
            continue

        if "**场景**" in line or "**教训**" in line:
            block = []
            while i < len(lines) and lines[i].strip():
                block.append(lines[i].strip())
                i += 1
            for b in block:
                if "**下次**" in b or "**行动**" in b:
                    rule = re.sub(r"\*\*[^*]+\*\*[:：]\s*", "", b)
                    rule = re.sub(r"^[-*]\s*", "", rule).strip()
                    if len(rule) > 15:
                        insights.append(rule)
                        break
            continue

        if "：" in line or ":" in line:
            parts = re.split(r"[:：]", line, 1)
            if len(parts) == 2:
                title = parts[0].strip()
                content_part = parts[1].strip()
                if len(title) < 30 and len(content_part) > 20:
                    rule = f"{title} -> {content_part[:80]}"
                    insights.append(rule)
                    i += 1
                    continue

        if any(
            sig in line
            for sig in ["->", "必须", "禁止", "应该", "不应该", "改用", "先用", "优先"]
        ):
            if line.startswith(("-", "*", ">")):
                clean = re.sub(r"^[-*>]\s*", "", line).strip()
                clean = re.sub(r"\*\*(.+?)\*\*", r"\1", clean)
                if len(clean) > 15 and not clean.startswith("#"):
                    insights.append(clean)

        i += 1

    return insights[:20]


def group_insights_by_topic(files_with_insights: list) -> dict:
    groups = defaultdict(list)
    for item in files_with_insights:
        topic = item["topic"].replace("_", " ")
        groups[topic].extend(item["insights"])
    return dict(groups)


# ── 去重（同主题内） ──────────────────────────────────────────────────────


def _extract_keywords(text):
    stopwords = {
        "的",
        "了",
        "在",
        "是",
        "和",
        "与",
        "或",
        "等",
        "中",
        "时",
        "用",
        "要",
        "可以",
        "需要",
        "这",
        "那",
        "有",
        "为",
        "到",
        "说",
        "会",
        "就",
        "都",
        "而",
        "及",
        "以",
        "但",
        "也",
        "不",
        "从",
        "对",
        "把",
        "被",
        "让",
        "给",
        "向",
        "由",
        "于",
        "将",
        "使",
        "得",
        "着",
        "过",
        "来",
        "去",
        "上",
        "下",
    }
    words = re.findall(r"[\w]+", text)
    return set(w for w in words if len(w) > 1 and w not in stopwords)


def _similarity(text1, text2):
    kw1 = _extract_keywords(text1)
    kw2 = _extract_keywords(text2)
    if not kw1 or not kw2:
        return 0.0
    intersection = len(kw1 & kw2)
    union = len(kw1 | kw2)
    return intersection / union if union > 0 else 0.0


def deduplicate_insights(insights: list) -> list:
    """同主题内去重：精确去重 + 语义去重"""
    if not insights:
        return []

    # 精确去重
    seen = set()
    result = []
    for ins in insights:
        key = re.sub(r"\s+", "", ins.lower())
        if key not in seen:
            seen.add(key)
            result.append(ins)

    # 语义去重（Jaccard > 0.6）
    merged = []
    skip = set()
    for i, ins1 in enumerate(result):
        if i in skip:
            continue
        similar = [ins1]
        for j, ins2 in enumerate(result[i + 1 :], start=i + 1):
            if j in skip:
                continue
            if _similarity(ins1, ins2) > 0.6:
                similar.append(ins2)
                skip.add(j)
        best = max(similar, key=len)
        merged.append(best)

    return merged


# ── 跨主题合并 ────────────────────────────────────────────────────────────


def merge_similar_rules(grouped: dict, threshold: float = 0.65) -> dict:
    """
    跨主题合并：遍历不同主题，将语义相似的规则合并到一个主题下。
    保留更长的主题名作为主主题，短名主题的规则迁移过去。
    返回合并后的 grouped dict。
    """
    topics = list(grouped.keys())
    merged_into = {}  # topic -> 主主题名
    result = defaultdict(list)

    # 建立主题之间的相似度关系
    for i, t1 in enumerate(topics):
        if t1 in merged_into:
            continue
        canonical = t1
        result[canonical].extend(grouped[t1])

        for t2 in topics[i + 1 :]:
            if t2 in merged_into:
                continue
            # 比较两个主题的代表规则（各取前2条）的平均相似度
            reps1 = grouped[t1][:2]
            reps2 = grouped[t2][:2]
            sims = []
            for r1 in reps1:
                for r2 in reps2:
                    sims.append(_similarity(r1, r2))
            avg_sim = sum(sims) / len(sims) if sims else 0.0

            if avg_sim >= threshold:
                # 合并：规则迁移到 canonical 主题
                result[canonical].extend(grouped[t2])
                merged_into[t2] = canonical

    if merged_into:
        merged_pairs = ", ".join(f"{k}->{v}" for k, v in merged_into.items())
        print(f"  跨主题合并: {merged_pairs}")

    return dict(result)


# ── 热冷分离 ──────────────────────────────────────────────────────────────


def split_hot_cold_rules(grouped: dict, learnings_dir: Path = None) -> tuple:
    """
    根据规则元数据（置信度、触发次数、最近触发时间）将规则分为热/冷两组。
    热规则：置信度 >= HOT_CONFIDENCE_THRESHOLD 或 触发次数 >= HOT_TRIGGER_MIN
            或 7天内新创建的规则（NEW_RULE_PROTECTION_DAYS）
    冷规则：其余（含超过 COLD_STALE_DAYS 天未触发的）
    返回 (hot_grouped, cold_grouped)
    """
    metadata = load_metadata()
    stale_rules = set(get_stale_rules(days=COLD_STALE_DAYS))

    hot = defaultdict(list)
    cold = defaultdict(list)

    for topic, insights in grouped.items():
        rule_id = f"rule_auto_{re.sub(r'[^a-z0-9_]', '_', topic.lower())}"
        meta = metadata.get(rule_id, {})
        confidence = meta.get("confidence", 0.5)
        triggered_count = meta.get("total", 0)  # V3.4.0 修复: triggered_count -> total

        is_hot = (
            confidence >= HOT_CONFIDENCE_THRESHOLD or triggered_count >= HOT_TRIGGER_MIN
        )

        # V3.4.0 新增: 7天内新创建的规则进入热规则
        is_recent = False
        if not is_hot and learnings_dir:
            from datetime import datetime, timedelta
            seven_days_ago = datetime.now() - timedelta(days=NEW_RULE_PROTECTION_DAYS)
            # 查找对应的 learnings 文件
            for f in learnings_dir.glob("*.md"):
                if topic.lower().replace(" ", "-") in f.stem.lower():
                    try:
                        file_time = datetime.fromtimestamp(f.stat().st_mtime)
                        if file_time >= seven_days_ago:
                            is_recent = True
                            break
                    except Exception:
                        pass
            if is_recent:
                is_hot = True

        is_cold_stale = rule_id in stale_rules

        if is_cold_stale:
            cold[topic].extend(insights)
        elif is_hot:
            hot[topic].extend(insights)
        else:
            # 未分类的默认归冷（保守策略）
            cold[topic].extend(insights)

    return dict(hot), dict(cold)


# ── 文档生成 ──────────────────────────────────────────────────────────────


def _build_rules_section(
    grouped: dict, title: str, generated_at: str, days: int
) -> str:
    """构建规则文档的公共方法"""
    lines = [
        f"# {title}",
        f"> 由 evolve_rules.py 生成 · {generated_at} · 覆盖最近 {days} 天 learnings",
        "",
        "---",
        "",
    ]

    if not grouped:
        lines += ["> 暂无可提炼的规律，继续积累 learnings 中...", ""]
        return "\n".join(lines)

    metadata = load_metadata()

    weighted_topics = []
    for topic, insights in sorted(grouped.items()):
        deduped = deduplicate_insights(insights)
        if not deduped:
            continue
        rule_id = f"rule_auto_{re.sub(r'[^a-z0-9_]', '_', topic.lower())}"
        rule_meta = metadata.get(rule_id, {})
        confidence = rule_meta.get("confidence", 0.5)
        triggered_count = rule_meta.get("triggered_count", 0)
        weight = confidence * (1 + math.log(triggered_count + 1))
        weighted_topics.append((topic, deduped, weight, confidence, triggered_count))

    weighted_topics.sort(key=lambda x: x[2], reverse=True)

    for topic, deduped, weight, confidence, triggered_count in weighted_topics:
        lines.append(f"## {topic}")
        if confidence > 0 or triggered_count > 0:
            lines.append(
                f"> 置信度: {confidence:.2f} | 触发: {triggered_count} 次 | 权重: {weight:.2f}"
            )
        lines.append("")
        for ins in deduped:
            lines.append(f"- {ins}")
        lines.append("")

    total_raw = sum(len(v) for v in grouped.values())
    total_deduped = sum(len(deduped) for _, deduped, *_ in weighted_topics)
    lines += [
        "---",
        f"*共 {total_raw} 条原始洞察 / {total_deduped} 条去重后 / {len(weighted_topics)} 个主题*",
    ]

    return "\n".join(lines)


def generate_rules_document(grouped: dict, generated_at: str, days: int) -> dict:
    """
    生成规则文档，返回 {"all": str, "hot": str, "cold": str}
    all  → auto_learned_rules.md（全部规则）
    hot  → auto_learned_rules_hot.md（热规则）
    cold → auto_learned_rules_cold.md（冷规则）
    """
    metadata = load_metadata()
    stale_rules = set(get_stale_rules(days=90))

    # 过滤低质量主题
    filtered = {}
    for topic, insights in grouped.items():
        rule_id = f"rule_auto_{re.sub(r'[^a-z0-9_]', '_', topic.lower())}"
        if rule_id in stale_rules:
            continue
        rule_meta = metadata.get(rule_id, {})
        if rule_meta.get("confidence", 0.5) < 0.3:
            continue
        filtered[topic] = insights

    # 热冷分离（V3.4.0: 传入 learnings_dir 以支持新规则保护）
    hot_grouped, cold_grouped = split_hot_cold_rules(filtered, LEARNINGS_DIR)

    # 生成三个文档
    doc_all = _build_rules_section(filtered, "自动学习规则快照", generated_at, days)
    doc_hot = _build_rules_section(
        hot_grouped, "热规则（高频/高置信度）", generated_at, days
    )
    doc_cold = _build_rules_section(
        cold_grouped, "冷规则（低频/归档参考）", generated_at, days
    )

    # 截断检查
    if doc_all.count("\n") + 1 > MAX_RULES_LINES:
        trimmed = [
            "# 自动学习规则快照（精简版）",
            f"> 由 evolve_rules.py 生成 · {generated_at} · 内容超过 {MAX_RULES_LINES} 行，已自动精简",
            "",
        ]
        weighted = []
        for topic, insights in sorted(filtered.items()):
            deduped = deduplicate_insights(insights)
            if not deduped:
                continue
            rule_id = f"rule_auto_{re.sub(r'[^a-z0-9_]', '_', topic.lower())}"
            # 使用时间衰减权重
            weight = get_effective_weight(rule_id)
            meta = metadata.get(rule_id, {})
            conf = meta.get("confidence", 0.5)
            weighted.append((topic, deduped, conf, weight))
        weighted.sort(key=lambda x: x[3], reverse=True)
        for topic, deduped, conf, _ in weighted[:20]:
            if deduped:
                trimmed.append(f"- **{topic}** (置信度:{conf:.2f}): {deduped[0]}")
        trimmed += ["", f"*精简版，共 {len(weighted)} 个主题*"]
        doc_all = "\n".join(trimmed)

    return {"all": doc_all, "hot": doc_hot, "cold": doc_cold}


def generate_learning_entry(grouped: dict, file_count: int, generated_at: str) -> str:
    total_raw = sum(len(v) for v in grouped.values())
    total_deduped = sum(len(deduplicate_insights(v)) for v in grouped.values())

    lines = [
        f"## {generated_at} - 每日进化提炼",
        "",
        f"- 扫描文件：{file_count} 个",
        f"- 原始洞察：{total_raw} 条",
        f"- 去重后：{total_deduped} 条",
        f"- 涵盖主题：{list(grouped.keys())}",
        "",
    ]
    if grouped:
        lines.append("### 高频规律（每个主题第一条）")
        for topic, insights in list(grouped.items())[:5]:
            deduped = deduplicate_insights(insights)
            if deduped:
                lines.append(f"- **{topic}**：{deduped[0]}")
    return "\n".join(lines)


def atomic_write(filepath: Path, content: str):
    tmp = filepath.with_suffix(filepath.suffix + ".tmp")
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, filepath)


# ── AGENTS-rules.md 生成（注入 LLM 决策回路）──────────────────────────────

AGENTS_RULES_FILE = WORKSPACE / "AGENTS-rules.md"

# 每个主题只保留一条最佳洞察（按优先级）
TOP_RULE_SIGNALS = [
    "->",
    "必须",
    "禁止",
    "应该",
    "不应该",
    "改用",
    "先用",
    "优先",
    "教训",
    "下次",
    "关键",
    "坑",
    "注意",
    "避免",
]


def _pick_best_insight(insights: list) -> str:
    """从多条洞察中选取最佳（最长且含优先级信号词）"""
    if not insights:
        return ""
    scored = []
    for ins in insights:
        score = sum(1 for sig in TOP_RULE_SIGNALS if sig in ins)
        scored.append((score, len(ins), ins))
    scored.sort(reverse=True)
    return scored[0][2]


def _generate_agents_rules_file(grouped: dict, now_str: str):
    """
    将最佳洞察写入 AGENTS-rules.md，确保 LLM 每次会话强制加载。
    每个主题只保留一条最佳洞察，保持文件精简。
    """
    lines = [
        "AGENTS-rules.md（行为规则 · 自动生成 · 每次会话 L1 必载）",
        "",
        f"> 生成时间: {now_str} · 覆盖最近 7 天 learnings",
        "",
        "---",
        "",
    ]

    for topic, insights in sorted(grouped.items()):
        deduped = deduplicate_insights(insights)
        if not deduped:
            continue
        best = _pick_best_insight(deduped)
        if best:
            lines.append(f"- **{topic}**: {best}")

    lines.append("")
    lines.append(f"*共 {len(grouped)} 个主题 · 自动生成 · 请勿手动修改*")

    content = "\n".join(lines)
    atomic_write(AGENTS_RULES_FILE, content)
    print(f"  AGENTS-rules.md 已更新: {len(grouped)} 个主题注入 LLM 决策回路")


def _compute_insights_hash(files_with_insights: list) -> str:
    """计算洞察内容的指纹哈希，用于增量检测"""
    content_parts = []
    for item in sorted(files_with_insights, key=lambda x: x.get("topic", "")):
        content_parts.append(item.get("topic", ""))
        for ins in sorted(item.get("insights", [])):
            content_parts.append(ins)
    return hashlib.md5("|".join(content_parts).encode("utf-8")).hexdigest()


def main():
    parser = argparse.ArgumentParser(description="每日学习提炼 -> 自动生成行为规则")
    parser.add_argument(
        "--days", type=int, default=7, help="扫描最近N天的 learnings（默认7）"
    )
    parser.add_argument("--all", action="store_true", help="扫描全部历史 learnings")
    parser.add_argument("--force", action="store_true", help="强制执行，跳过增量检测")
    args = parser.parse_args()

    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    today_str = now.strftime("%Y-%m-%d")

    print("=" * 60)
    print(" evolve_rules - 每日自动进化提炼")
    print(f"   范围：{'全部' if args.all else f'最近 {args.days} 天'}")
    print("=" * 60)

    # 1. 收集文件
    files = collect_learning_files(days=args.days, all_files=args.all)
    permanent = collect_permanent_learning_files()
    if permanent:
        files = list(permanent) + list(files)
        print(
            f" 发现 {len(files)} 个 learning 文件（含 {len(permanent)} 个永久知识文件）"
        )
    else:
        print(f" 发现 {len(files)} 个 learning 文件")

    if not files:
        print(" 无 learnings 可处理，跳过")
        return 0

    # 2. 提取洞察
    files_with_insights = []
    for item in files:
        insights = extract_insights_from_file(item["path"])
        if insights:
            insights = insights[:5]
            files_with_insights.append(
                {
                    "date": item["date"].isoformat(),
                    "topic": item["topic"],
                    "insights": insights,
                    "file": str(item["path"]),
                }
            )
            try:
                content = item["path"].read_text(encoding="utf-8")
                update_from_learning(content, str(item["path"].name))
            except Exception as e:
                print(f"  ⚠️ knowledge_map 更新失败: {item['path'].name}: {e}")

    total_insights = sum(len(i["insights"]) for i in files_with_insights)
    print(f" 提取洞察：{total_insights} 条（来自 {len(files_with_insights)} 个文件）")

    # 2b. 增量检测：如果洞察内容与上次完全相同，跳过版本升级
    current_hash = _compute_insights_hash(files_with_insights)
    evo_log = load_evolution_log()
    last_hash = evo_log.get("last_insights_hash", "")

    if not args.force and current_hash == last_hash and last_hash:
        print(f" 洞察内容与上次相同（hash={current_hash[:8]}），跳过版本升级")
        print(f" 使用 --force 强制执行")
        return 0

    # 3. 按主题聚合
    grouped = group_insights_by_topic(files_with_insights)

    # 4. 跨主题合并
    print(" 执行跨主题合并...")
    grouped = merge_similar_rules(grouped, threshold=0.65)

    # 5. 生成规则文档（含热冷分离）
    docs = generate_rules_document(grouped, now_str, args.days)
    atomic_write(AUTO_RULES_FILE, docs["all"])
    atomic_write(AUTO_RULES_HOT_FILE, docs["hot"])
    atomic_write(AUTO_RULES_COLD_FILE, docs["cold"])
    print(f" 规则快照已更新：{AUTO_RULES_FILE}")
    print(f" 热规则：{AUTO_RULES_HOT_FILE}")
    print(f" 冷规则：{AUTO_RULES_COLD_FILE}")

    # 6. 清理 pending review
    if PENDING_REVIEW_FILE.exists():
        PENDING_REVIEW_FILE.unlink()

    # 7. 写入提炼记录
    entry_content = generate_learning_entry(grouped, len(files), now_str)
    entry_file = LEARNINGS_DIR / f"{today_str}-进化摘要.md"
    LEARNINGS_DIR.mkdir(parents=True, exist_ok=True)
    if entry_file.exists():
        existing = entry_file.read_text(encoding="utf-8")
        entry_content = existing.rstrip("\n") + "\n\n" + entry_content
    atomic_write(entry_file, entry_content)
    print(f" 提炼记录已写入：{entry_file.name}")

    # 8. 自动晋升规则到 RULES-CORE.md
    SKIP_PROMOTE_TOPICS = {
        "LEARNINGS",
        "daily-report-sigterm",
        "自动观察",
        "full-auto-correction",
        "group-chat-isolation-fix",
        "tavily-search-config",
    }
    rules_core = WORKSPACE / "RULES-CORE.md"
    if rules_core.exists() and grouped:
        promoted = []
        for topic, insights in grouped.items():
            if topic in SKIP_PROMOTE_TOPICS:
                continue
            deduped = deduplicate_insights(insights)
            if not deduped:
                continue
            action_signals = [
                "->",
                "必须",
                "禁止",
                "应该",
                "不应该",
                "用",
                "先",
                "再",
                "改用",
            ]
            best = next(
                (
                    i
                    for i in deduped
                    if any(s in i for s in action_signals) and len(i) > 20
                ),
                next((i for i in deduped if len(i) > 20), deduped[0]),
            )
            promoted.append(f"- {best}")
            rule_id = f"rule_auto_{re.sub(r'[^a-z0-9_]', '_', topic.lower())}"
            register_rule(rule_id, source="auto_evolve", initial_confidence=0.7)

        if promoted:
            existing = rules_core.read_text(encoding="utf-8")
            today_marker = f"## 自动进化规则 ({now_str[:10]})"
            if today_marker in existing:
                print(f" 今日规则已写入，跳过重复追加")
            else:
                new_lines = []
                for line in promoted:
                    key = line[2:32]
                    if key in existing:
                        continue
                    new_lines.append(line)
                if new_lines:
                    new_section = f"\n\n{today_marker}\n" + "\n".join(new_lines)
                    atomic_write(rules_core, existing.rstrip("\n") + new_section + "\n")
                    print(
                        f" 已自动晋升 {len(new_lines)} 条新规则到 RULES-CORE.md（跳过 {len(promoted) - len(new_lines)} 条已有）"
                    )
                else:
                    print(f" 所有规则已存在，无需追加")

    # 9. 更新进化日志
    evo_log["rules_version"] = evo_log.get("rules_version", 0) + 1
    evo_log["total_learnings_processed"] = evo_log.get(
        "total_learnings_processed", 0
    ) + len(files_with_insights)
    evo_log["last_insights_hash"] = current_hash
    evo_log["events"].append(
        {
            "timestamp": now_str,
            "event": "daily_evolve",
            "files_scanned": len(files),
            "insights_extracted": total_insights,
            "topics": list(grouped.keys()),
            "rules_version": evo_log["rules_version"],
            "output": str(AUTO_RULES_FILE),
        }
    )
    if len(evo_log["events"]) > 200:
        evo_log["events"] = evo_log["events"][-200:]
    save_evolution_log(evo_log)

    # ── 10. 生成 AGENTS-rules.md（注入 LLM 决策回路）───────────────
    _generate_agents_rules_file(grouped, now_str)

    print(
        f"\n 进化日志更新：版本 v{evo_log['rules_version']}，"
        f"累计处理 {evo_log['total_learnings_processed']} 条学习记录"
    )
    print("=" * 60)

    log_operation(
        tool="evolve_rules",
        action="evolve",
        params={
            "days": args.days,
            "all": args.all,
            "files": len(files),
            "insights": total_insights,
        },
        result=f"进化完成：提取{total_insights}条洞察，版本v{evo_log['rules_version']}",
        success=total_insights > 0,
        insights=f"- 从{len(files)}个文件中提取了{total_insights}条洞察，涵盖{len(grouped)}个主题"
        if total_insights > 0
        else None,
    )

    # 11. learnings 索引维护（滞后 >3 天则重建，保持索引新鲜度）
    try:
        index_file = WORKSPACE / "state" / "learnings_index.json"
        needs_rebuild = False
        if index_file.exists():
            try:
                data = json.loads(index_file.read_text(encoding="utf-8"))
                gen_time = datetime.fromisoformat(
                    data.get("generated_at", "1970-01-01")
                )
                lag_days = (datetime.now() - gen_time).days
                needs_rebuild = lag_days > 3
            except Exception:
                needs_rebuild = True
        else:
            needs_rebuild = True

        if needs_rebuild:
            print("\n  - 重建 learnings 索引（滞后超过 3 天）...")
            from rebuild_learnings_index import full_rebuild

            result = full_rebuild()
            print(
                f"    已重建: 扫描 {result.get('files_scanned', 0)} 文件, {result.get('entries', 0)} 条目"
            )
    except Exception as e:
        print(f"    ⚠️ 索引重建失败: {e}")

    # 12. 记录版本变更到 CHANGELOG
    try:
        from version_changelog import (
            record_rules_evolution,
            auto_check_and_upgrade_rules_version,
        )

        # 记录本次演化
        record_rules_evolution(
            insights_count=total_insights, themes=list(grouped.keys())
        )

        # 自动检查并升级规则版本
        # 从 unified_state.json 获取真实的触发数据
        metadata = load_metadata()
        triggers_data = metadata.get("triggers", {})
        total_triggers = sum(m.get("total", 0) for m in triggers_data.values())

        upgrade_result = auto_check_and_upgrade_rules_version(
            themes=list(grouped.keys()),
            stats={
                "insights": total_insights,
                "triggers": total_triggers,  # 从 unified_state.json 读取
                "evolutions": 0,
            },
        )
        print(f"\n  版本记录已同步: CHANGELOG.md")
        print(f"  当前规则版本: {upgrade_result['new_version']}")

    except Exception as e:
        print(f"    ⚠️ 版本记录失败: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
