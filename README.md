# OpenClaw — Self-Evolving AI Agent Framework

**OpenClaw** is a lightweight, self-evolving AI agent framework that continuously learns from interactions, refines its own rules, and improves decision quality over time — with zero token overhead.

---

## 核心特性 / Core Features

- **自我进化** / Self-Evolution：从每次对话中提炼经验，自动优化行为规则
- **学习质量评分** / Learning Quality Scoring：过滤低质量经验，确保只有高价值规则被固化
- **原子性状态管理** / Atomic State Management：文件锁 + 临时文件机制，防止状态损坏
- **版本化缓存** / Versioned Cache：TTL + 版本号双重验证，保证数据一致性
- **零 Token 开销** / Zero Token Overhead：所有学习和进化逻辑在本地执行

---

## 目录结构 / Structure

```
tools/
├── core/
│   ├── state_manager.py        # 基础状态管理
│   ├── state_manager_v2.py     # 原子性状态管理（推荐）
│   ├── auto_state_manager.py   # 自动状态管理
│   ├── cache_manager.py        # 版本化缓存管理
│   ├── file_utils.py           # 文件工具函数
│   ├── time_utils.py           # 时间工具函数
│   └── json_utils.py           # JSON 工具函数
├── learning/
│   ├── learning_core.py        # 学习引擎核心
│   ├── rule_evolver.py         # 规则演化引擎
│   ├── outcome_tracker.py      # 结果追踪
│   └── knowledge_store.py      # 知识存储
├── llm/
│   └── llm_processor.py        # LLM 处理器
├── learning_quality_scorer.py  # 学习质量评分
└── evolve_rules.py             # 规则演化主程序
```

---

## 快速上手 / Quick Start

```python
from tools.state_manager_v2 import StateManagerV2
from tools.learning_quality_scorer import LearningQualityScorer
from tools.evolve_rules import evolve_rules

# 初始化状态管理
state = StateManagerV2("./state")

# 评估学习质量
scorer = LearningQualityScorer()
result = scorer.score("path/to/learning_file.md")
if result["should_learn"]:
    evolve_rules()
```

---

## 设计理念 / Design Philosophy

OpenClaw 的核心理念是**最小干预、最大进化**：

1. **分层加载**：按需加载，最小化内存和 token 消耗
2. **WAL 协议**：先写文件后执行，保证关键信息不丢失
3. **质量门控**：学习质量评分过滤低价值经验
4. **原子操作**：所有状态写入都是原子性的，防止数据损坏

---

## 版本 / Version

**v3.5.1** — 安全加固与性能优化

- 消除数据泄露和命令注入风险
- Dashboard 性能提升 75%
- 新增原子性状态写入和版本化缓存

---

## 许可证 / License

MIT License — 自由使用、修改和分发。
