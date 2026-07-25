"""Prep Agent — generates the InterviewContext and QuestionPlan before the interview.

Flow:
1. Load the position's seed questions from the question bank
2. If a JD is provided, use LLM to personalise (tune questions, add JD-specific questions)
3. Build the QuestionPlan with time budgets
4. Write everything into the InterviewContext blackboard
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from app.models.interview import (
    InterviewContext,
    InterviewStatus,
    QuestionPlan,
    Question,
    CompetencyDimension,
    PhaseEnum,
)
from app.services.llm_service import llm_invoke, has_real_llm

# Path to the seed question bank
_QUESTION_BANK_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "question_bank.json"

PERSONALISE_SYSTEM = """你是一个专业的面试出题官。根据候选人简历调整原始面试题目，
使其更贴合候选人的技术栈和项目经验。比如候选人用过 Vue，就把 React 相关题改成 Vue 相关。
保持题目难度和考察维度不变。只返回调整后的题目文本，不要添加解释。"""


class PrepAgent:
    """Prep-phase agent responsible for building the interview plan."""

    def __init__(self):
        self._bank: dict = {}
        self._load_bank()

    def _load_bank(self):
        if _QUESTION_BANK_PATH.exists():
            with open(_QUESTION_BANK_PATH, "r", encoding="utf-8") as f:
                self._bank = json.load(f)

    # ── Public API ──────────────────────────────────────

    async def run(
        self,
        position: str,
        resume_text: Optional[str] = None,
    ) -> InterviewContext:
        """Execute the Prep pipeline and return a ready-to-start InterviewContext.

        Args:
            position: Target job position
            resume_text: Parsed resume content (for personalised questions)
        """
        ctx = InterviewContext(status=InterviewStatus.PREP)
        ctx.candidate_profile = self._build_profile(position, resume_text)
        if resume_text:
            ctx.jd_summary = await self._summarise_resume(resume_text)

        # Build competency dimensions for this position
        ctx.competency_dimensions = list(CompetencyDimension)

        # Build question plan
        ctx.question_plan = await self._build_plan(position, resume_text)

        return ctx

    # ── Internal ─────────────────────────────────────────

    def _build_profile(self, position: str, resume_text: Optional[str] = None) -> str:
        if resume_text:
            return f"候选人职位方向: {position}\n简历摘要: {resume_text[:200]}..."
        return f"候选人职位方向: {position}"

    async def _summarise_resume(self, resume_text: str) -> str:
        """Use LLM to extract a concise summary from the resume."""
        if not has_real_llm():
            return f"简历内容({len(resume_text)}字): {resume_text[:300]}"
        try:
            prompt = f"请用100字以内总结这份简历的技术栈和核心经验:\n{resume_text[:2000]}"
            result = await llm_invoke(prompt, system_prompt="你是简历分析专家。简洁总结。")
            return result.strip()[:500]
        except Exception:
            return resume_text[:500]

    async def _build_plan(
        self, position: str, resume_text: Optional[str] = None
    ) -> QuestionPlan:
        """Build the QuestionPlan: select seed questions + personalise via LLM."""
        plan = QuestionPlan(position=position)

        # Phase order (without Q&A — that's reactive)
        phase_map = {
            PhaseEnum.INTRODUCTION: "introduction",
            PhaseEnum.PROJECT_DEEP_DIVE: "project_deep_dive",
            PhaseEnum.TECH_FOUNDATION: "tech_foundation",
        }

        # Get seed questions from bank
        seed_questions = self._bank.get(position, {})
        if not seed_questions:
            # Fallback: generic questions for unknown positions
            seed_questions = self._bank.get("前端工程师", {})

        for phase, bank_key in phase_map.items():
            q_texts = seed_questions.get(bank_key, ["请说说你的理解。"])
            for i, text in enumerate(q_texts):
                # Determine competency dimension
                dim = self._infer_dimension(phase, text, i)

                # Personalise based on resume
                final_text = text
                if resume_text:
                    final_text = await self._personalise_question(text, resume_text)

                plan.questions.append(Question(
                    phase=phase,
                    text=final_text,
                    competency_dimension=dim,
                    follow_up_strategy=self._pick_follow_up_strategy(phase, dim),
                ))

        return plan

    def _infer_dimension(self, phase: PhaseEnum, text: str, index: int) -> CompetencyDimension:
        """Map a question to its primary competency dimension."""
        if phase == PhaseEnum.PROJECT_DEEP_DIVE:
            return CompetencyDimension.PROJECT_EXPERIENCE
        elif phase == PhaseEnum.TECH_FOUNDATION:
            return CompetencyDimension.TECH_DEPTH
        elif phase == PhaseEnum.INTRODUCTION:
            return CompetencyDimension.COMMUNICATION
        return CompetencyDimension.ROLE_FIT

    def _pick_follow_up_strategy(self, phase: PhaseEnum, dim: CompetencyDimension) -> str:
        """Determine the follow-up strategy for a question."""
        if phase == PhaseEnum.PROJECT_DEEP_DIVE:
            return "如果回答提到具体技术决策，追问'为什么选这个方案而不是其他方案'"
        if phase == PhaseEnum.TECH_FOUNDATION:
            return "如果回答停留于概念层面，追问'在实际项目中你是怎么用的'"
        return "如果回答过于简短，追问'能更具体地展开说说吗'"

    async def _personalise_question(self, original: str, resume_text: str) -> str:
        """Use LLM to personalise a seed question based on the candidate's resume."""
        if not resume_text or not has_real_llm():
            return original

        try:
            prompt = (
                f"候选人简历:\n{resume_text[:1000]}\n\n"
                f"原始题目:\n{original}\n\n"
                f"请根据候选人简历调整题目，使其更贴合候选人的技术栈和项目经验。"
            )
            result = await llm_invoke(prompt, system_prompt=PERSONALISE_SYSTEM)
            return result.strip() if result.strip() else original
        except Exception:
            return original
