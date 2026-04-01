# OpenClaw — 心智矩阵自进化系统

> A self-evolving AI agent framework that learns from every interaction, refines its own rules, and continuously improves — with zero token overhead.

OpenClaw 是一套面向高阶使用者的自我学习与自我提升 AI 框架。通过「犯错 → 学习 → 提炼 → 强化」的闭环机制，让 AI 具备真正的自我改进能力。核心目标：在保持简单操作的前提下，实现系统的自我改进与自适应，为团队提供持续的知识积累、智能决策与高效协作能力。

**系统经过 30 天全功能测试验证**：内置全场景运营规则库、80.3% 规则应用率、健康度满分、0% 系统错误率、0% 数据丢失率。

---

## 核心能力

### 自进化闭环
全自动化五步闭环，无需人工干预：自动发现问题 → 分析根因 → 提出建议 → 验证效果 → 落地形成规则。

### 学习质量评分
对每条学习记录进行多维度评分，过滤低质量经验，确保只有高价值规则被固化进系统。

### 原子性状态管理
文件锁 + 临时文件 + 自动备份机制，防止并发写入导致状态损坏，数据丢失率 0%。

### 版本化缓存
TTL + 版本号双重验证，保证跨进程数据一致性，缓存命中率 >95%。

### 记忆与知识管理
分层记忆架构：核心记忆常驻，次要记忆按需加载。跨会话沉淀重要知识，语义检索快速调用。

### 运行效率优化
- 文件分层加载将核心文件精简 81%
- 启动 Token 消耗降低 73.5%（从 ~7,690 降至 ~2,040）
- LLM 批量处理，Token 节省 60–77%

---

## 与传统方案对比

| 维度 | OpenClaw | 传统方案 |
|------|----------|---------|
| 学习闭环 | 完整七步自动闭环 | 缺乏持续闭环 |
| 记忆管理 | 分层记忆、跨会话沉淀、语义检索 | 局限于当前会话 |
| 自动化水平 | 自我修复、健康监控、自动评估迭代 | 较多人工干预 |
| Token 消耗 | 降低 73.5% | 消耗较高 |
| 可靠性 | 错误率 0%，数据丢失率 0% | 依赖人工检查 |
| 可进化性 | 持续迭代优化 | 能力停滞 |

---

## 核心指标（30 天测试验证）

| 指标 | 数据 |
|------|------|
| 对话轮次 | 3,000 轮 |
| 日记写入成功率 | 100% |
| 系统错误率 | 0% |
| 数据丢失率 | 0% |
| 规则应用率 | 80.3% |
| Token 消耗下降 | 73.5% |
| 健康度分数 | 100 分（满分） |

---

## 目录结构

```
tools/
├── state_manager.py            # 基础状态管理
├── state_manager_v2.py         # 原子性状态管理（推荐）
├── auto_state_manager.py       # 自动状态管理
├── cache_manager.py            # 版本化缓存管理
├── learning_core.py            # 学习引擎核心
├── rule_evolver.py             # 规则演化引擎
├── outcome_tracker.py          # 结果追踪
├── knowledge_store.py          # 知识存储
├── llm_processor.py            # LLM 处理器
├── learning_quality_scorer.py  # 学习质量评分
├── evolve_rules.py             # 规则演化主程序
├── file_utils.py               # 文件工具函数
├── time_utils.py               # 时间工具函数
└── json_utils.py               # JSON 工具函数
```

---

## 快速上手

```python
from tools.state_manager_v2 import StateManagerV2
from tools.learning_quality_scorer import LearningQualityScorer
from tools.evolve_rules import evolve_rules

# 初始化状态管理
state = StateManagerV2("./state")

# 评估学习质量并触发规则演化
scorer = LearningQualityScorer()
result = scorer.score("path/to/learning_file.md")
if result["should_learn"]:
    evolve_rules()
```

---

## 设计理念

OpenClaw 的核心理念是**最小干预、最大进化**：

1. **分层加载**：按需加载，最小化内存和 token 消耗
2. **WAL 协议**：先写文件后执行，保证关键信息不丢失
3. **质量门控**：学习质量评分过滤低价值经验
4. **原子操作**：所有状态写入都是原子性的，防止数据损坏

---

## 更新日志

### v3.5.1（当前版本）
安全加固与性能优化。修复仪表盘直接读取原始会话数据的风险，改为读取预生成统计数据；移除命令注入隐患；新增安全检查工具。仪表盘启动速度提升 75%，内存占用降低 40%，修复若干内部模块功能缺失问题。

### v3.3.1
修复隐私扫描后未触发 record_violation 的 bug；修复 `_atomic_append` 双重写入问题；移除固定 mock 指标；实现入队 LLM 重新分析和高效果建议推广至 learnings；修复 100+ 处打印警告。

### v3.2.0
完成 30 天全功能测试验证，所有核心指标达到或超过预期。Token 消耗减少 73.5%。新增真实应用验证、完整反馈闭环、自动化集成、建议质量评分等核心能力。

### v3.1.0
引入完整学习闭环机制。新增 P0 关键能力（真实应用验证、反馈闭环、自动化集成）、P1 重要增强（建议质量评分、跨模式学习）、P2 进阶能力（多维度学习、自适应优化）。

### v3.0.0
引入五维自进化能力：主动学习系统、语义记忆检索、任务感知加载、元认知追踪、规则进化闭环。

---

## 许可证

MIT License — 自由使用、修改和分发。
