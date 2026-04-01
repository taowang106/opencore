#!/usr/bin/env python3
"""
migrate_state.py - 状态迁移脚本
将现有的43个状态文件迁移到统一状态管理器

用法：
  python3 tools/core/migrate_state.py              # 执行迁移
  python3 tools/core/migrate_state.py --dry-run     # 预览迁移（不执行）
  python3 tools/core/migrate_state.py --rollback    # 回滚到迁移前状态
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.state_manager import StateManager

WORKSPACE = Path(
    os.environ.get("OPENCLAW_WORKSPACE", Path(__file__).parent.parent.parent)
)
STATE_DIR = WORKSPACE / "state"

# 迁移映射表：(源文件, 目标路径, 提取函数)
MIGRATIONS = [
    # 学习相关
    ("knowledge_map.json", "learning.knowledge_map", lambda d: d.get("domains", {})),
    (
        "crystallized_knowledge.json",
        "learning.crystallized_knowledge",
        lambda d: d.get("knowledge", []),
    ),
    (
        "learning_suggestions.json",
        "learning.learning_suggestions",
        lambda d: d.get("suggestions", []),
    ),
    (
        "learning_journey.json",
        "learning.learning_journey",
        lambda d: d.get("journey", []),
    ),
    ("meta_learning.json", "learning.meta_learning", lambda d: d),
    # 规则相关
    ("rule_violations.json", "rules.violations", lambda d: d.get("violations", [])),
    ("rules_metadata.json", "rules.metadata", lambda d: d.get("metadata", {})),
    ("rules_audit.json", "rules.audit_log", lambda d: d.get("entries", [])),
    (
        "evolution_log.json",
        "rules.evolution_log",
        lambda d: d.get("events", [])[-100:],
    ),  # 只保留最近100条
    (
        "experiments_applied.json",
        "rules.experiments_applied",
        lambda d: d.get("applied", []),
    ),
    # 系统状态
    (
        "health_check.json",
        "system.health",
        lambda d: d.get("checks", [{}])[-1] if d.get("checks") else {},
    ),
    (
        "operation_log.json",
        "system.operations",
        lambda d: d.get("operations", [])[-500:],
    ),  # 只保留最近500条
    (
        "behavior_patterns.json",
        "system.behavior_patterns",
        lambda d: d.get("patterns", []),
    ),
    ("context_stats.json", "system.context_stats", lambda d: d),
    # 会话相关
    (
        "sessions.json",
        "sessions.history",
        lambda d: d.get("sessions", [])[-50:],
    ),  # 只保留最近50条
    (
        "feedback_loop.json",
        "sessions.feedback",
        lambda d: d.get("feedbacks", [])[-100:],
    ),
    # 隐私相关
    (
        "privacy_violation_tracker.json",
        "privacy.violations",
        lambda d: d.get("violations", []),
    ),
    ("privacy_rules.json", "privacy.rules", lambda d: d),
    (
        "resolved_violations.json",
        "privacy.resolved",
        lambda d: d if isinstance(d, list) else d.get("resolved", []),
    ),
    # 实验相关
    ("experiments.json", "experiments.active", lambda d: d.get("experiments", [])),
    (
        "experiment_rollbacks.json",
        "experiments.rollbacks",
        lambda d: d.get("rollbacks", []),
    ),
    # 记忆相关
    ("memory_archive_index.json", "memory.archive_index", lambda d: d),
    ("memory_size_tracker.json", "memory.size_tracker", lambda d: d),
    # 备份相关
    ("backup_file_hashes.json", "system.backup_hashes", lambda d: d),
    ("backup_sync_log.json", "system.backup_sync_log", lambda d: d),
    ("backup_verification_report.json", "system.backup_verification", lambda d: d),
    # 其他
    ("heartbeat_last_run.json", "system.heartbeat_last_run", lambda d: d),
    ("recovery_log.json", "system.recovery_log", lambda d: d),
    ("recovery_queue.json", "system.recovery_queue", lambda d: d),
    ("tavily-usage.json", "system.tavily_usage", lambda d: d),
    ("people-updates.json", "system.people_updates", lambda d: d),
    ("cron-reminder.log", None, None),  # 不迁移，保留原文件
    ("aftergateway_credentials.json", None, None),  # 不迁移，保留原文件
    ("xiaping_credentials.json", None, None),  # 不迁移，保留原文件
    ("auto_learned_rules.md", None, None),  # 不迁移，保留为文件
    ("auto_learned_rules_hot.md", None, None),
    ("auto_learned_rules_cold.md", None, None),
    ("chroma_db", None, None),  # 目录，不迁移
]


def migrate(dry_run: bool = False):
    """执行迁移"""
    print("=" * 60)
    print(f"状态迁移 {'(预览模式)' if dry_run else ''}")
    print("=" * 60)

    manager = StateManager(WORKSPACE)

    if not dry_run:
        # 创建备份
        print("\n📦 创建备份...")
        manager.backup()
        print("✅ 备份完成")

    success_count = 0
    skip_count = 0
    error_count = 0

    print("\n🔄 开始迁移...")

    for filename, target_path, extractor in MIGRATIONS:
        source_file = STATE_DIR / filename

        # 跳过不迁移的文件
        if target_path is None:
            print(f"⏭️  跳过 {filename}（保留原文件）")
            skip_count += 1
            continue

        # 检查源文件是否存在
        if not source_file.exists():
            print(f"⏭️  跳过 {filename}（文件不存在）")
            skip_count += 1
            continue

        # 跳过目录
        if source_file.is_dir():
            print(f"⏭️  跳过 {filename}（是目录）")
            skip_count += 1
            continue

        try:
            # 读取源文件
            content = source_file.read_text(encoding="utf-8")

            # 尝试解析JSON
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                # 不是JSON文件，直接存储内容
                data = {"content": content}

            # 提取数据
            extracted = extractor(data) if extractor else data

            if dry_run:
                # 预览模式
                if isinstance(extracted, (list, dict)):
                    size = len(extracted)
                    print(f"✅ {filename} → {target_path} (大小: {size})")
                else:
                    print(f"✅ {filename} → {target_path}")
            else:
                # 执行迁移
                manager.set(target_path, extracted, atomic=False)
                print(f"✅ {filename} → {target_path}")

            success_count += 1

        except Exception as e:
            print(f"❌ {filename} 迁移失败: {e}")
            error_count += 1

    # 打印统计
    print("\n" + "=" * 60)
    print("迁移统计")
    print("=" * 60)
    print(f"✅ 成功: {success_count}")
    print(f"⏭️  跳过: {skip_count}")
    print(f"❌ 失败: {error_count}")
    print(f"📊 总计: {success_count + skip_count + error_count}")

    if not dry_run and error_count == 0:
        # 保存状态
        manager._atomic_write(manager._read_state())
        print("\n✅ 迁移完成！已保存到 unified_state.json")
    elif not dry_run and error_count > 0:
        print("\n⚠️ 迁移完成，但有错误。请检查后重试。")

    return success_count, skip_count, error_count


def rollback():
    """回滚到迁移前状态"""
    manager = StateManager(WORKSPACE)

    # 查找最新备份
    backups = sorted(manager.backup_dir.glob("state_*.json"))
    if not backups:
        print("❌ 没有可用的备份")
        return False

    latest_backup = backups[-1]
    print(f"🔄 回滚到: {latest_backup.name}")

    if manager.restore(str(latest_backup)):
        print("✅ 回滚成功")
        return True
    else:
        print("❌ 回滚失败")
        return False


def verify():
    """验证迁移结果"""
    manager = StateManager(WORKSPACE)

    print("=" * 60)
    print("验证迁移结果")
    print("=" * 60)

    # 检查关键路径
    critical_paths = [
        "learning.knowledge_map",
        "rules.violations",
        "system.health",
        "sessions.history",
        "privacy.violations",
    ]

    all_ok = True
    for path in critical_paths:
        value = manager.get(path)
        if value is not None:
            if isinstance(value, (list, dict)):
                print(f"✅ {path}: {len(value)} 条记录")
            else:
                print(f"✅ {path}: {value}")
        else:
            print(f"❌ {path}: 未找到")
            all_ok = False

    # 打印摘要
    print("\n📊 状态摘要:")
    summary = manager.get_summary()
    for key, value in summary.items():
        print(f"  {key}: {value}")

    return all_ok


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="状态迁移工具")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不执行迁移")
    parser.add_argument("--rollback", action="store_true", help="回滚到迁移前状态")
    parser.add_argument("--verify", action="store_true", help="验证迁移结果")

    args = parser.parse_args()

    if args.rollback:
        rollback()
    elif args.verify:
        verify()
    else:
        migrate(dry_run=args.dry_run)
