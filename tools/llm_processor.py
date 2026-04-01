#!/usr/bin/env python3
"""
llm_processor.py - 统一LLM处理器
合并llm_analyzer、llm_bridge、llm_client、auto_llm_processor、process_llm_queue等

特性：
- 统一接口：一个模块处理所有LLM相关操作
- 批量处理：减少API调用次数
- 低Token消耗：精简prompt + 批量处理
- 自动队列管理：自动清理和优化
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
STATE_DIR = WORKSPACE / "state"
QUEUE_FILE = STATE_DIR / "llm_analysis_queue.json"


class AnalysisRequest:
    """LLM分析请求"""

    def __init__(self, request_type: str, context: Dict, prompt: str = None):
        self.id = f"{request_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.type = request_type
        self.context = context
        self.prompt = prompt or self._generate_prompt(request_type, context)
        self.created = datetime.now().isoformat()
        self.status = "pending"
        self.result = None

    def _generate_prompt(self, request_type: str, context: Dict) -> str:
        """根据类型生成prompt"""
        if request_type == "failure_analysis":
            return (
                f"分析失败：\n"
                f"工具: {context.get('tool', 'unknown')}\n"
                f"错误: {context.get('error_message', '')[:100]}\n"
                f"请给出: root_cause, solution (各50字内)"
            )
        elif request_type == "rule_conflict":
            return (
                f"规则冲突：\n"
                f"规则1: {context.get('rule1', '')}\n"
                f"规则2: {context.get('rule2', '')}\n"
                f"请给出: is_conflict (true/false), reason (30字内)"
            )
        elif request_type == "knowledge_extraction":
            topics = context.get("key_topics", [])[:3]
            return (
                f"知识提取：\n"
                f"主题: {', '.join(topics)}\n"
                f"请给出: key_insights (3条，各30字内)"
            )
        else:
            return f"分析请求：{json.dumps(context, ensure_ascii=False)[:200]}"

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "type": self.type,
            "context": self.context,
            "prompt": self.prompt,
            "created": self.created,
            "status": self.status,
            "result": self.result,
        }


class LLMProcessor:
    """统一LLM处理器"""

    def __init__(self):
        self.state = get_state_manager()

    # ============================================================
    # 队列管理
    # ============================================================

    def queue_analysis(self, request: AnalysisRequest) -> str:
        """将分析请求加入队列"""
        STATE_DIR.mkdir(parents=True, exist_ok=True)

        # 加载现有队列
        if QUEUE_FILE.exists():
            try:
                data = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"⚠️ [LLMProcessor] 队列加载失败，使用空队列: {e}")
                data = {"requests": []}
        else:
            data = {"requests": []}

        # 添加新请求
        data["requests"].append(request.to_dict())

        # 只保留最近50个pending请求
        pending = [r for r in data["requests"] if r["status"] == "pending"]
        completed = [r for r in data["requests"] if r["status"] == "completed"]
        data["requests"] = pending[-50:] + completed[-20:]

        # 原子写入
        tmp = QUEUE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, QUEUE_FILE)

        return request.id

    def get_pending(self, limit: int = 10) -> List[Dict]:
        """获取待处理的分析请求"""
        if not QUEUE_FILE.exists():
            return []

        try:
            data = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
            pending = [
                r for r in data.get("requests", []) if r.get("status") == "pending"
            ]
            return pending[:limit]
        except Exception as e:
            print(f"⚠️ [LLMProcessor] 获取待分析失败: {e}")
            return []

    def get_next_batch(self, limit: int = 5) -> List[Dict]:
        """获取下一批待处理的分析请求（批量处理）"""
        return self.get_pending(limit)

    def complete_analysis(self, request_id: str, result: Any):
        """标记分析完成"""
        if not QUEUE_FILE.exists():
            return

        try:
            data = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return

        # 更新请求状态
        for req in data.get("requests", []):
            if req.get("id") == request_id:
                req["status"] = "completed"
                req["result"] = result
                req["completed_at"] = datetime.now().isoformat()
                break

        # 原子写入
        tmp = QUEUE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, QUEUE_FILE)

    def fail_analysis(self, request_id: str, error: str):
        """标记分析失败"""
        if not QUEUE_FILE.exists():
            return

        try:
            data = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return

        # 更新请求状态
        for req in data.get("requests", []):
            if req.get("id") == request_id:
                req["status"] = "failed"
                req["error"] = error
                req["failed_at"] = datetime.now().isoformat()
                break

        # 原子写入
        tmp = QUEUE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, QUEUE_FILE)

    # ============================================================
    # 批量处理
    # ============================================================

    def format_batch_prompt(self, requests: List[Dict]) -> str:
        """
        格式化批量分析请求为单个prompt
        优化：减少token消耗
        """
        if not requests:
            return ""

        prompt_parts = ["请分析以下问题，对每个问题给出简洁的JSON格式回答：\n"]

        for i, req in enumerate(requests, 1):
            req_type = req.get("type", "unknown")
            context = req.get("context", {})

            if req_type == "failure_analysis":
                prompt_parts.append(
                    f"\n{i}. 失败分析 (ID: {req['id']})\n"
                    f"工具: {context.get('tool')}\n"
                    f"错误: {context.get('error_message', '')[:100]}\n"
                    f"请给出: root_cause, solution (各50字内)\n"
                )

            elif req_type == "rule_conflict":
                prompt_parts.append(
                    f"\n{i}. 规则冲突 (ID: {req['id']})\n"
                    f"规则1: {context.get('rule1')}\n"
                    f"规则2: {context.get('rule2')}\n"
                    f"请给出: is_conflict (true/false), reason (30字内)\n"
                )

            elif req_type == "knowledge_extraction":
                topics = context.get("key_topics", [])[:3]
                prompt_parts.append(
                    f"\n{i}. 知识提取 (ID: {req['id']})\n"
                    f"主题: {', '.join(topics)}\n"
                    f"请给出: key_insights (3条，各30字内)\n"
                )

            else:
                prompt_parts.append(
                    f"\n{i}. {req_type} (ID: {req['id']})\n"
                    f"上下文: {json.dumps(context, ensure_ascii=False)[:100]}\n"
                )

        prompt_parts.append("\n请以JSON数组格式回答，每个元素包含id和分析结果。")

        return "".join(prompt_parts)

    def process_batch(self, requests: List[Dict], results: List[Dict]):
        """处理批量分析结果"""
        for result in results:
            request_id = result.get("id")
            if request_id:
                self.complete_analysis(request_id, result)

    # ============================================================
    # 自动处理
    # ============================================================

    def auto_process(self, limit: int = 5) -> Dict:
        """自动处理队列"""
        # 获取待处理请求
        pending = self.get_pending(limit)

        if not pending:
            return {"processed": 0, "message": "无待处理请求"}

        # 格式化批量prompt
        batch_prompt = self.format_batch_prompt(pending)

        # 这里应该调用LLM
        # 由于我们无法直接调用LLM，返回提示
        return {
            "processed": 0,
            "pending": len(pending),
            "prompt": batch_prompt,
            "message": "请在主会话中处理此prompt",
        }

    # ============================================================
    # 队列清理
    # ============================================================

    def cleanup_queue(self, days: int = 7):
        """清理旧的队列条目"""
        if not QUEUE_FILE.exists():
            return

        try:
            data = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return

        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        # 保留pending和最近的completed
        requests = data.get("requests", [])
        cleaned = []

        for req in requests:
            if req.get("status") == "pending":
                cleaned.append(req)
            elif req.get("completed_at", "") > cutoff:
                cleaned.append(req)

        data["requests"] = cleaned

        # 原子写入
        tmp = QUEUE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, QUEUE_FILE)

    def get_queue_stats(self) -> Dict:
        """获取队列统计"""
        if not QUEUE_FILE.exists():
            return {"pending": 0, "completed": 0, "failed": 0}

        try:
            data = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
            requests = data.get("requests", [])

            pending = len([r for r in requests if r.get("status") == "pending"])
            completed = len([r for r in requests if r.get("status") == "completed"])
            failed = len([r for r in requests if r.get("status") == "failed"])

            return {
                "pending": pending,
                "completed": completed,
                "failed": failed,
                "total": len(requests),
            }
        except Exception:
            return {"pending": 0, "completed": 0, "failed": 0}


# 从datetime导入timedelta
from datetime import timedelta

# 全局实例
_llm_processor = None


def get_llm_processor() -> LLMProcessor:
    """获取全局LLM处理器实例"""
    global _llm_processor
    if _llm_processor is None:
        _llm_processor = LLMProcessor()
    return _llm_processor


# ============================================================
# 便捷函数
# ============================================================


def queue_analysis(request_type: str, context: Dict, prompt: str = None) -> str:
    """加入分析队列"""
    processor = get_llm_processor()
    request = AnalysisRequest(request_type, context, prompt)
    return processor.queue_analysis(request)


def get_pending_analyses(limit: int = 10) -> List[Dict]:
    """获取待分析请求"""
    return get_llm_processor().get_pending(limit)


def complete_analysis(request_id: str, result: Any):
    """标记分析完成"""
    get_llm_processor().complete_analysis(request_id, result)


def process_queue(limit: int = 10) -> Dict:
    """处理队列"""
    return get_llm_processor().auto_process(limit)


if __name__ == "__main__":
    # 测试
    processor = LLMProcessor()

    # 测试创建请求
    request = AnalysisRequest(
        "failure_analysis", {"tool": "write_memory", "error_message": "权限拒绝"}
    )
    request_id = processor.queue_analysis(request)
    print(f"✅ 创建请求: {request_id}")

    # 测试获取待处理
    pending = processor.get_pending(5)
    print(f"✅ 待处理请求: {len(pending)}")

    # 测试统计
    stats = processor.get_queue_stats()
    print(f"✅ 队列统计: {stats}")
