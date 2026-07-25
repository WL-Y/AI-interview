"""InterviewContext — the shared blackboard across Prep / Live / Post phases."""

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
    POST = "post"      # 评分已完成
    ABORTED = "aborted"


class RoleEnum(StrEnum):
    INTERVIEWER = "interviewer"
    CANDIDATE = "candidate"
    SYSTEM = "system"


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

    # ── Post writes ───────────────────────────────────
    scorecard: Optional[ScoreCard] = None

    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
