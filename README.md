# AI 模拟面试 Agent

> 简历驱动 · 自适应追问 · 多维度评估 · 语音优先

基于三模块架构（Interviewer + Evaluator + Adaptive State）的智能模拟面试平台。AI 不再是机械地按题库出题，而是根据每一轮回答动态调整策略——追问深度、挑战背诵、降低难度、切换方向——真实还原资深面试官的判断力。

## ✨ 核心功能

- **简历驱动** — 上传 PDF/DOCX/TXT 简历，AI 自动提取技术栈并初始化技能评估模型
- **自适应面试** — Evaluator（隐藏评估器）对每轮回答进行 5 维度 0-4 评分，Interviewer 根据评估结果动态决定下一题
- **半结构化面试** — 自我介绍 → 项目深挖 → 技术基础 → 反问，框架内有灵活追问
- **技能追踪** — 实时追踪每项技能的分值 + 置信度（Score/Confidence），优先探测信息增益最大的方向
- **语音优先** — 语音交互为主，文字兜底，模拟真实面试体验
- **智能评分** — 面试后生成 4 维度 × 5 分制评分报告（技术深度 / 项目经验 / 表达沟通 / 岗位匹配）
- **Mock-First** — 不配置任何 API Key 也能跑通完整面试流程，零成本开发调试

## 🏗️ 架构

```
                         ┌──────────────────────┐
                         │     Candidate         │
                         │     候选人回答          │
                         └──────────┬───────────┘
                                    │ Answer
                                    ▼
┌─────────────┐     ┌──────────────────────────────┐     ┌──────────────┐
│   Next.js    │────▶│        FastAPI 后端           │────▶│  DeepSeek    │
│   前端       │◀────│                              │◀────│  (主 LLM)    │
└─────────────┘     │  ┌────────────────────────┐  │     ├──────────────┤
                    │  │    Evaluator (隐藏)      │  │     │  通义千问     │
                    │  │  5维度评分 + 理解类型    │  │     │  (兜底 LLM)   │
                    │  │  证据提取 + 缺口检测     │  │     └──────────────┘
                    │  └───────────┬────────────┘  │
                    │              │ Assessment     │
                    │  ┌───────────▼────────────┐  │     ┌──────────────┐
                    │  │   Adaptive State        │  │     │  火山引擎     │
                    │  │  Skills + Confidence    │  │────▶│  STT + TTS   │
                    │  │  Coverage + Priority    │  │◀────│              │
                    │  └───────────┬────────────┘  │     └──────────────┘
                    │              │ State          │
                    │  ┌───────────▼────────────┐  │
                    │  │    Interviewer          │  │
                    │  │  动态生成下一题           │  │
                    │  └────────────────────────┘  │
                    └──────────────────────────────┘
```

### 核心闭环（v2 自适应）

```
Candidate Answer
      ↓
Evaluator Call (LLM) → structured assessment JSON
      ↓
Update AdaptiveState (skill scores, confidence, coverage)
      ↓
Interviewer Call (LLM) → next question, dynamically generated
      ↓
Next Question
```

**每轮 2 次 LLM 调用**，一次评估一次出题，解耦避免"出题者自己评分"的评估漂移。

### 三阶段流水线

| 阶段 | 时机 | 职责 |
|------|------|------|
| **Prep** | 面试前 | 解析简历 → 提取技术栈 → 初始化技能评估模型 → 生成候选人画像 |
| **Live** | 面试中 | Evaluator 评估每轮回答 → 更新技能置信度 → Interviewer 动态出题 → 阶段切换 |
| **Post** | 面试后 | LLM 评估完整 transcript → 4 维度评分 → 亮点/缺陷/改进建议 |

### LLM 三级降级

```
DeepSeek V4-Pro (10s 超时) → 通义千问 (兜底) → Mock (启发式)
```

## 🚀 快速启动

### 前置条件

- Python 3.12+ + conda
- Node.js 18+
- Docker Desktop（可选，运行 PG/Redis/LiveKit）

### 1. 启动基础设施

```bash
docker compose up -d
```

### 2. 启动后端

```bash
cd backend
conda create -n ai-interview python=3.12 -y
conda activate ai-interview
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 3. 启动前端

```bash
cd frontend
npm install --legacy-peer-deps
npm run dev
```

浏览器打开 **http://localhost:3000** 即可使用。

## 🔧 配置

在 `backend/.env` 中配置 API Key（不配置则自动使用 Mock 模式）：

```bash
# LLM（至少配一个）
DEEPSEEK_API_KEY=sk-xxx
QWEN_API_KEY=sk-xxx

# 语音（可选）
VOLCANO_STT_APP_ID=xxx
VOLCANO_STT_TOKEN=xxx
VOLCANO_TTS_TOKEN=xxx
```

## 📂 项目结构

```
AI-面试/
├── backend/
│   ├── app/
│   │   ├── agent/
│   │   │   ├── prep/agent.py            # Prep Agent（简历解析 + 技能初始化）
│   │   │   ├── live/
│   │   │   │   ├── agent.py             # Live Agent（自适应面试主循环）
│   │   │   │   └── evaluator.py         # Evaluator Agent（隐藏评估器，5维度评分）
│   │   │   └── post/agent.py            # Post Agent（4维度评分报告）
│   │   ├── api/interview.py             # REST + WebSocket + Voice 端点
│   │   ├── models/interview.py          # 核心数据模型（含自适应状态）
│   │   ├── core/                        # 配置、数据库、启动自检
│   │   └── services/
│   │       ├── llm_service.py           # DeepSeek/Qwen/Mock 三级降级
│   │       ├── resume_parser.py         # PDF/DOCX/TXT 简历解析（有序块遍历）
│   │       ├── json_utils.py            # 共享 JSON 提取工具
│   │       ├── livekit/worker.py        # 语音面试 Worker
│   │       └── voice/
│   │           ├── audio_utils.py        # PCM/WAV 转换
│   │           ├── volcano_stt.py        # 火山引擎 STT
│   │           ├── volcano_tts.py        # 火山引擎 TTS
│   │           └── factory.py            # Provider 工厂
│   ├── data/question_bank.json          # 种子题库（LLM 失败时兜底）
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── app/                         # Next.js App Router
│   │   ├── components/
│   │   │   ├── LandingScreen.tsx         # 简历上传页
│   │   │   ├── InterviewScreen.tsx       # 面试界面（自适应进度条）
│   │   │   ├── ReportScreen.tsx          # 评分报告页
│   │   │   ├── ErrorBoundary.tsx
│   │   │   └── Toast.tsx
│   │   └── stores/interview.ts          # Zustand 状态管理（自适应类型）
│   └── package.json
├── adaptive_interview_agent.md           # 自适应面试 Agent 设计文档
├── resume_parser_optimization.md         # 简历解析优化文档
└── docker-compose.yml                   # PostgreSQL + Redis + LiveKit
```

## 🎯 自适应面试核心设计

### Evaluator（隐藏评估器）

对每轮回答进行结构化评估，**候选人不看到分析过程**：

- **5 维度 0-4 评分**：正确性、深度、推理能力、工程判断、表达沟通
- **理解类型分类**：真正理解 / 部分理解 / 背诵答案 / 侥幸猜对 / 理解错误 / 证据不足
- **证据提取**：强证据（真正证明能力）、弱证据（可能正确但不充分）、问题证据（错误/矛盾/遗漏）
- **缺口检测**：找出最值得追问的一个关键知识缺口
- **动作推荐**：DEEPEN / CLARIFY / CHALLENGE / HINT / EASIER / ADVANCE / VERIFY_EXPERIENCE / END

### Adaptive State（自适应状态）

- **技能追踪**：每项技能维护 Score (0-100) + Confidence (0-1)，**两者分离**——低置信度≠低能力，而是"需要更多证据"
- **覆盖度**：追踪每项技能的考察覆盖程度
- **难度自适应**：根据连续表现动态调整题目难度
- **优先级公式**：`Priority = Importance × Uncertainty × RemainingCoverage`

### Interviewer（自适应面试官）

根据 Evaluator 的评估结果和当前 State，动态决定下一题：

| 评估结果 | 面试官行为 |
|----------|-----------|
| 回答正确且深入 | 追问更深层机制 / 反例 / 工程权衡 |
| 回答部分正确 | 围绕缺口继续追问：为什么？依赖什么条件？ |
| 像背诵答案 | 挑战：改变假设 / 要求推导 / 构造反例 |
| 明显不会 | 给一次 hint → 仍无法回答 → 降低难度或切换主题 |
| 证据充分 | 进入信息增益最大的下一技能 |

## 📋 面试阶段

| 阶段 | 时长 | 说明 |
|------|------|------|
| 📝 自我介绍 | ~2 min | 了解背景和技术方向 |
| 🔍 项目深挖 | ~8 min | 验证项目真实性、个人贡献、技术决策 |
| 💡 技术基础 | ~8 min | 考察简历技术栈的底层原理理解 |
| 🙋 反问环节 | ~2 min | 候选人提问 |

## 🛠️ 技术栈

| 层 | 技术 |
|----|------|
| 前端 | Next.js 16 + React 19 + Zustand + Tailwind CSS |
| 后端 | Python 3.12 + FastAPI + httpx + Pydantic |
| LLM | DeepSeek V4-Pro（主）+ 通义千问 Qwen3 Max（兜底） |
| 简历解析 | PyPDF2 + python-docx（PDF/DOCX/TXT，魔数检测 + 有序块遍历） |
| 语音 STT | 火山引擎（豆包）流式语音识别 |
| 语音 TTS | 火山引擎（豆包）语音合成 2.0（PCM → WAV 封装） |
| 实时传输 | LiveKit (WebRTC) |
| 数据 | PostgreSQL + Redis |
| 部署 | Docker Compose |

## 📝 开发路线

- [x] M0 — 项目骨架搭建
- [x] M1 — 文本面试闭环（Mock 全流程）
- [x] M2 — 语音管道接入（火山引擎 + LiveKit）
- [x] M3 — 真实 LLM 切换（DeepSeek/Qwen 三级降级）
- [x] M4 — 打磨上线（错误处理 + 会话管理 + Docker）
- [x] M5 — 自适应 Agent v2（Evaluator + Adaptive State + 动态出题）
- [x] M6 — 简历解析优化（有序块遍历 + 结构输出 + 质量检测）
- [ ] M7 — 语音路径修复 + 前端自适应 UI 完善
- [ ] M8 — 岗位加权终面评分 + Hiring Recommendation

## 📄 License

MIT
