"""InterviewContext — the shared blackboard across Prep / Live / Post phases.

Adaptive Interview Agent models (v2):
- SkillEstimate: Bayesian-like per-skill belief (score 0-100 + confidence 0-1)
- EvaluatorOutput: structured assessment from the hidden Evaluator agent
- AdaptiveState: the evolving interview state that drives question selection
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ════════════════════════════════════════════════════════════════
# Enums
# ════════════════════════════════════════════════════════════════

class PhaseEnum(StrEnum):
    INTRODUCTION = "introduction"       # 自我介绍
    PROJECT_DEEP_DIVE = "project_deep_dive"  # 项目深挖
    TECH_FOUNDATION = "tech_foundation"  # 技术基础
    Q_AND_A = "q_and_a"                 # 反问环节


class CompetencyDimension(StrEnum):
    TECH_DEPTH = "tech_depth"           # 技术深度
    PROJECT_EXPERIENCE = "project_experience"  # 项目经验
    COMMUNICATION = "communication"     # 表达沟通
    ROLE_FIT = "role_fit"               # 岗位匹配度


class InterviewStatus(StrEnum):
    PREP = "prep"      # Prep 已完成，等待开始
    LIVE = "live"      # 面试进行中
    PAUSED = "paused"  # 面试暂停中
    POST = "post"      # 评分已完成
    ABORTED = "aborted"


class RoleEnum(StrEnum):
    INTERVIEWER = "interviewer"
    CANDIDATE = "candidate"
    SYSTEM = "system"


class UnderstandingType(StrEnum):
    """How the evaluator classifies a candidate's answer."""
    GENUINE = "genuine_understanding"
    PARTIAL = "partial_understanding"
    MEMORIZED = "memorized_answer"
    LUCKY_GUESS = "lucky_guess"
    MISCONCEPTION = "misconception"
    INSUFFICIENT = "insufficient_evidence"


class EvalAction(StrEnum):
    """Recommended next action from the evaluator."""
    DEEPEN = "DEEPEN"               # Answer good → probe deeper
    CLARIFY = "CLARIFY"             # Answer vague → ask for specifics
    CHALLENGE = "CHALLENGE"         # Seems memorized → counterexample / derivation
    HINT = "HINT"                   # Candidate close → small hint
    EASIER = "EASIER"               # Too hard → reduce difficulty
    ADVANCE = "ADVANCE"             # Enough evidence → next topic
    VERIFY_EXPERIENCE = "VERIFY_EXPERIENCE"  # Check if candidate really did it
    END = "END"                     # Sufficient evidence overall


# ════════════════════════════════════════════════════════════════
# Adaptive State — skill tracking (doc Section 4, 9)
# ════════════════════════════════════════════════════════════════

class SkillEstimate(BaseModel):
    """Bayesian-like per-skill belief. Score and confidence are separate —
    low confidence means 'need more evidence', not 'candidate is bad'. (doc §9)"""
    score: int = 50             # 0-100
    confidence: float = 0.1     # 0-1
    evidence_count: int = 0
    importance: float = 0.5     # 0-1 — how important this skill is for the role


class EvaluatorOutput(BaseModel):
    """Structured output from the hidden Evaluator agent. (doc Section 5)"""
    # Assessment scores (0-4 per doc §Step 2)
    correctness: int = 0
    depth: int = 0
    reasoning: int = 0
    practicality: int = 0
    communication: int = 0

    # Classification
    understanding_type: UnderstandingType = UnderstandingType.INSUFFICIENT

    # Evidence
    strong_evidence: list[str] = []
    weak_evidence: list[str] = []
    problematic_evidence: list[str] = []

    # Gap detection
    detected_gap: str = ""

    # Skill updates (delta to apply to adaptive state)
    skill_updates: dict[str, SkillEstimate] = {}

    # Recommendation for Interviewer
    recommended_action: EvalAction = EvalAction.ADVANCE
    recommended_probe: str = ""


class AdaptiveState(BaseModel):
    """The evolving interview state that drives adaptive questioning. (doc Section 4)"""
    # Per-skill estimates — key: skill name (e.g. "database", "system_design")
    skills: dict[str, SkillEstimate] = {}

    # Per-skill coverage ratio (0-1)
    coverage: dict[str, float] = {}

    # Current topic tracking
    current_topic: str = ""
    turns_on_topic: int = 0
    max_turns_per_topic: int = 4     # Safety cap — don't dwell forever
    hints_given: int = 0

    # Phase-level tracking
    phase_topics_covered: list[str] = []

    # Difficulty adaptation
    current_difficulty: int = 3      # 1-5, adjusted dynamically


# ════════════════════════════════════════════════════════════════
# Question Plan
# ════════════════════════════════════════════════════════════════

class Question(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:8])
    phase: PhaseEnum
    text: str
    competency_dimension: CompetencyDimension
    follow_up_strategy: str = ""       # 追问策略描述
    follow_up_asked: bool = False      # 是否已追问过
    draft_score: Optional[int] = None  # Live 阶段草稿分 (1-5)


class QuestionPlan(BaseModel):
    position: str                       # 岗位方向
    questions: list[Question] = []
    time_budget: dict[str, int] = Field(default_factory=lambda: {
        "introduction": 120,            # 秒
        "project_deep_dive": 480,
        "tech_foundation": 480,
        "q_and_a": 120,
    })


# ════════════════════════════════════════════════════════════════
# Turn / Transcript
# ════════════════════════════════════════════════════════════════

class Turn(BaseModel):
    role: RoleEnum
    content: str
    phase: PhaseEnum
    timestamp: datetime = Field(default_factory=datetime.now)
    question_id: Optional[str] = None   # 绑定的题目 id


# ════════════════════════════════════════════════════════════════
# Answer Record
# ════════════════════════════════════════════════════════════════

class AnswerRecord(BaseModel):
    question_id: str
    question_text: str
    answer_summary: str                 # LLM 摘要
    dimension: CompetencyDimension
    draft_score: Optional[int] = None   # 1-5
    notes: str = ""                     # 面试官备注
    candidate_answer: str = ""          # 候选人原始回答（供前端展示反馈）


# ════════════════════════════════════════════════════════════════
# ScoreCard (Post phase output)
# ════════════════════════════════════════════════════════════════

class DimensionScore(BaseModel):
    dimension: CompetencyDimension
    score: int                          # 1-5
    comment: str


class ScoreCard(BaseModel):
    overall_score: float                # 加权总分
    dimension_scores: list[DimensionScore] = []
    strengths: list[str] = []
    weaknesses: list[str] = []
    improvement_plan: str = ""


# ════════════════════════════════════════════════════════════════
# InterviewContext — the central blackboard
# ════════════════════════════════════════════════════════════════

class InterviewContext(BaseModel):
    session_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    status: InterviewStatus = InterviewStatus.PREP

    # ── Prep writes ───────────────────────────────────
    candidate_profile: str = ""         # 候选人画像摘要
    jd_summary: str = ""                # JD 关键要求
    competency_dimensions: list[CompetencyDimension] = []
    question_plan: Optional[QuestionPlan] = None

    # ── Live writes ───────────────────────────────────
    current_phase: PhaseEnum = PhaseEnum.INTRODUCTION
    current_question_index: int = 0
    transcript: list[Turn] = []
    answer_records: list[AnswerRecord] = []

    # ── Adaptive state (v2) ────────────────────────────
    adaptive_state: Optional[AdaptiveState] = None  # The evolving skill/coverage tracker
    last_evaluation: Optional[EvaluatorOutput] = None  # Most recent evaluator assessment
    adaptive_mode: bool = True           # Whether to use adaptive questioning (vs static plan)

    # ── Progress tracking ──────────────────────────────
    total_questions: int = 0            # Total questions (estimated in adaptive mode)
    answered_questions: int = 0         # Number of questions answered so far
    elapsed_seconds: int = 0            # Elapsed time in seconds
    paused_at: Optional[datetime] = None

    # ── Post writes ───────────────────────────────────
    scorecard: Optional[ScoreCard] = None

    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
