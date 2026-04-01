#!/usr/bin/env python3
"""
knowledge_store.py - 知识存储系统
合并knowledge_map、crystallized_knowledge、query_learnings、rebuild_learnings_index

特性：
- 统一知识存储
- 高效查询
- 自动索引
- 低Token消耗
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.state_manager import get_state_manager

WORKSPACE = Path(
    os.environ.get("OPENCLAW_WORKSPACE", Path(__file__).parent.parent.parent)
)
LEARNINGS_DIR = WORKSPACE / ".learnings"


class KnowledgeStore:
    """知识存储系统"""

    def __init__(self):
        self.state = get_state_manager()
        self._index = {}
        self._index_loaded = False

    # ============================================================
    # 知识查询
    # ============================================================

    def query(self, keyword: str, limit: int = 10) -> List[Dict]:
        """查询知识"""
        # 确保索引已加载
        if not self._index_loaded:
            self._load_index()

        # 在索引中搜索
        results = []
        keyword_lower = keyword.lower()

        for entry_id, entry in self._index.items():
            if keyword_lower in entry.get("content", "").lower():
                results.append(entry)
                if len(results) >= limit:
                    break

        return results

    def query_by_domain(self, domain: str, limit: int = 10) -> List[Dict]:
        """按领域查询"""
        km = self.state.get("learning.knowledge_map", {})

        if domain not in km:
            return []

        domain_info = km[domain]
        sources = domain_info.get("sources", [])

        # 读取源文件
        results = []
        for source in sources[:limit]:
            source_path = LEARNINGS_DIR / source
            if source_path.exists():
                try:
                    content = source_path.read_text(encoding="utf-8")
                    results.append(
                        {
                            "file": source,
                            "content": content[:500],  # 只返回前500字符
                            "domain": domain,
                        }
                    )
                except Exception:
                    pass

        return results

    def get_summary(self) -> Dict:
        """获取知识库摘要"""
        km = self.state.get("learning.knowledge_map", {})
        crystallized = self.state.get("learning.crystallized_knowledge", [])

        return {
            "domains": len(km),
            "total_insights": sum(d.get("experience_count", 0) for d in km.values()),
            "crystallized_count": len(crystallized),
            "top_domains": self._get_top_domains(km, 5),
        }

    # ============================================================
    # 索引管理
    # ============================================================

    def _load_index(self):
        """加载索引"""
        index_file = LEARNINGS_DIR / "index.json"

        if index_file.exists():
            try:
                data = json.loads(index_file.read_text(encoding="utf-8"))
                self._index = {e["id"]: e for e in data.get("entries", [])}
                self._index_loaded = True
                return
            except Exception:
                pass

        # 索引不存在或损坏，重建
        self.rebuild_index()

    def rebuild_index(self):
        """重建索引"""
        print("🔄 重建知识索引...")

        self._index = {}
        entries = []

        # 扫描.learnings目录
        for file_path in LEARNINGS_DIR.glob("*.md"):
            if file_path.name in ["LEARNINGS.md", "index.json"]:
                continue

            try:
                content = file_path.read_text(encoding="utf-8")

                # 提取关键词
                keywords = self._extract_keywords(content)

                entry = {
                    "id": file_path.stem,
                    "file": file_path.name,
                    "content": content[:1000],  # 只索引前1000字符
                    "keywords": keywords,
                    "timestamp": datetime.fromtimestamp(
                        file_path.stat().st_mtime
                    ).isoformat(),
                }

                entries.append(entry)
                self._index[entry["id"]] = entry

            except Exception as e:
                print(f"⚠️ 读取 {file_path.name} 失败: {e}")

        # 保存索引
        index_data = {
            "version": "1.0",
            "generated_at": datetime.now().isoformat(),
            "entries": entries,
            "total_entries": len(entries),
        }

        index_file = LEARNINGS_DIR / "index.json"
        index_file.write_text(
            json.dumps(index_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        self._index_loaded = True
        print(f"✅ 索引重建完成: {len(entries)} 条记录")

    def incremental_update(self, file_path: str):
        """增量更新索引"""
        path = Path(file_path)

        if not path.exists() or path.suffix != ".md":
            return

        try:
            content = path.read_text(encoding="utf-8")
            keywords = self._extract_keywords(content)

            entry = {
                "id": path.stem,
                "file": path.name,
                "content": content[:1000],
                "keywords": keywords,
                "timestamp": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
            }

            self._index[entry["id"]] = entry

            # 保存更新后的索引
            self._save_index()

        except Exception as e:
            print(f"⚠️ 增量更新 {path.name} 失败: {e}")

    def _save_index(self):
        """保存索引"""
        entries = list(self._index.values())

        index_data = {
            "version": "1.0",
            "generated_at": datetime.now().isoformat(),
            "entries": entries,
            "total_entries": len(entries),
        }

        index_file = LEARNINGS_DIR / "index.json"
        index_file.write_text(
            json.dumps(index_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ============================================================
    # 辅助函数
    # ============================================================

    def _extract_keywords(self, content: str) -> List[str]:
        """提取关键词"""
        keywords = []

        # 简单的关键词提取
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("- **") and "**" in line:
                # 提取加粗的关键词
                start = line.find("- **") + 4
                end = line.find("**", start)
                if end > start:
                    keywords.append(line[start:end])

        return keywords[:10]  # 最多返回10个关键词

    def _get_top_domains(self, km: Dict, limit: int) -> List[Dict]:
        """获取顶级领域"""
        domains = []
        for domain, info in km.items():
            domains.append(
                {
                    "name": domain,
                    "confidence": info.get("confidence", 0),
                    "experience_count": info.get("experience_count", 0),
                }
            )

        # 按置信度排序
        domains.sort(key=lambda x: x["confidence"], reverse=True)
        return domains[:limit]


# 全局实例
_knowledge_store = None


def get_knowledge_store() -> KnowledgeStore:
    """获取全局知识存储实例"""
    global _knowledge_store
    if _knowledge_store is None:
        _knowledge_store = KnowledgeStore()
    return _knowledge_store


if __name__ == "__main__":
    # 测试
    store = KnowledgeStore()

    # 测试查询
    results = store.query("python")
    print(f"✅ 查询结果: {len(results)} 条")

    # 测试摘要
    summary = store.get_summary()
    print(f"✅ 知识库摘要: {summary}")
