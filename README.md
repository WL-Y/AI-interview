# AI 模拟面试 Agent

> 语音优先 · 半结构化 · 智能评分 · 简历个性化

一个面向求职者的 AI 模拟面试练习平台。上传简历，选择岗位方向，AI 面试官会根据你的背景进行个性化的半结构化面试，并在面试结束后给出 4 维度的评分报告。

## ✨ 核心功能

- **简历驱动** — 上传 PDF/DOCX/TXT 简历，AI 自动提取技术栈并定制面试题
- **半结构化面试** — 自我介绍 → 项目深挖 → 技术基础 → 反问，框架内有灵活追问
- **语音优先** — 语音交互为主，文字兜底，模拟真实面试体验
- **智能评分** — 面试后生成 4 维度 × 5 分制评分报告（技术深度 / 项目经验 / 表达沟通 / 岗位匹配）
- **Mock-First** — 不配置任何 API Key 也能跑通完整面试流程，零成本开发调试

## 🏗️ 架构

```
┌─────────────┐     ┌──────────────────────────────┐     ┌──────────────┐
│   Next.js    │────▶│        FastAPI 后端           │────▶│  DeepSeek    │
│   前端       │◀────│                              │◀────│  (主 LLM)    │
└─────────────┘     │  ┌────── ┌────── ┌──────┐   │     ├──────────────┤
                    │  │ Prep │ Live  │ Post │   │     │  通义千问     │
                    │  │Agent │ Agent │ Agent│   │     │  (兜底 LLM)   │
                    │  └──────┴──────┴──────┘   │     └──────────────┘
                    │          │                   │
                    │    ┌─────┴─────┐            │     ┌──────────────┐
                    │    │ LiveKit   │            │────▶│  火山引擎     │
                    │    │ (实时语音)│            │◀────│  STT + TTS   │
                    │    └───────────┘            │     └──────────────┘
                    └──────────────────────────────┘
```

### 三阶段流水线

| 阶段 | 时机 | 职责 |
|------|------|------|
| **Prep** | 面试前 | 解析简历 → 加载题库 → LLM 个性化调整 → 生成 QuestionPlan |
| **Live** | 面试中 | 按计划出题 → 动态追问 → 环节切换 → 草稿打分 |
| **Post** | 面试后 | LLM 评估完整 transcript → 4 维度评分 → 亮点/缺陷/改进建议 |

### LLM 三级降级

```
DeepSeek V4-Pro (3s 超时) → 通义千问 (兜底) → Mock (启发式)
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

# 语音（M2 阶段需要）
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
│   │   │   ├── prep/agent.py       # Prep Agent（简历解析 + 出题计划）
│   │   │   ├── live/agent.py       # Live Agent（追问/环节切换/草稿评分）
│   │   │   └── post/agent.py       # Post Agent（4维度评分报告）
│   │   ├── api/interview.py        # REST + WebSocket + Voice 端点
│   │   ├── models/interview.py     # InterviewContext 核心数据模型
│   │   ├── core/                   # 配置、数据库、启动自检
│   │   └── services/
│   │       ├── llm_service.py      # DeepSeek/Qwen/Mock 三级降级
│   │       ├── resume_parser.py    # PDF/DOCX/TXT 简历解析
│   │       └── voice/              # STT/TTS Provider-Adapter
│   ├── data/question_bank.json     # 6岗位 × 100+ 种子面试题
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── app/                    # Next.js App Router
│   │   ├── components/             # Landing/Interview/Report/ErrorBoundary/Toast
│   │   └── stores/interview.ts     # Zustand 状态管理
│   └── package.json
└── docker-compose.yml              # PostgreSQL + Redis + LiveKit
```

## 📋 支持的岗位

- 前端工程师
- 后端工程师
- 算法工程师
- 数据分析师
- 产品经理
- DevOps/SRE

## 🛠️ 技术栈

| 层 | 技术 |
|----|------|
| 前端 | Next.js 16 + React 19 + Zustand + Tailwind CSS |
| 后端 | Python 3.12 + FastAPI + httpx |
| LLM | DeepSeek V4-Pro（主）+ 通义千问 Qwen3 Max（兜底） |
| 语音 STT | 火山引擎（豆包）流式语音识别 |
| 语音 TTS | 火山引擎（豆包）语音合成 2.0 |
| 实时传输 | LiveKit (WebRTC) |
| 数据 | PostgreSQL + Redis |
| 部署 | Docker Compose |

## 📝 开发路线

- [x] M0 — 项目骨架搭建
- [x] M1 — 文本面试闭环（Mock 全流程）
- [x] M2 — 语音管道接入（火山引擎 + LiveKit）
- [x] M3 — 真实 LLM 切换（DeepSeek/Qwen 三级降级）
- [x] M4 — 打磨上线（错误处理 + 会话管理 + Docker）

## 📄 License

MIT
