"""Prep Agent — generates the InterviewContext and QuestionPlan before the interview.

Flow:
1. If a resume is provided, LLM generates questions entirely from the resume content
2. If no resume, fall back to the seed question bank
3. Build the QuestionPlan with time budgets
4. Write everything into the InterviewContext blackboard
"""

from __future__ import annotations

import json
import logging
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
from app.services.llm_service import llm_invoke, has_real_llm, BATCH_TIMEOUT
from app.services.json_utils import extract_json

logger = logging.getLogger(__name__)

# Path to the seed question bank (fallback when no resume)
_QUESTION_BANK_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "question_bank.json"

# ── Prompt: generate questions FROM resume ─────────────────

RESUME_DRIVEN_SYSTEM = """你是一个资深面试官，同时也是一位"简历解剖师"。你的任务是**逐字逐句研读候选人简历**，然后为这个人量身设计一套面试题。

**工作流程**：
1. 先识别候选人最擅长的技术栈（从简历中的技术关键词提取）
2. 识别候选人履历中的每一个关键项目、每个数字指标
3. 推断候选人匹配的技术岗位
4. 围绕以上信息生成面试题

**出题规则**：
- 自我介绍环节（2题）：题目中引用简历里的具体公司和项目名，引导候选人展开
- 项目深挖环节（3-4题）：每道题深挖简历中一个具体项目。必须引用项目中的技术名词和数据
- 技术基础环节（2-3题）：只问简历中列出的技术栈的底层原理，不问简历没有的技术

**绝对禁止**：
- 不要问"请介绍一下你的项目"这种泛泛的问题
- 不要问候选人没用过的技术
- 不要用模板化的追问策略

**必须做到**：
- 每道题都包含简历中的具体细节（公司名/项目名/技术名/数字）
- 追问策略是具体的、技术性的深挖方向
- 候选人读题时会觉得"这个面试官把我的简历吃透了"

返回 JSON（只返回 JSON，不要任何解释或 markdown）：
{"questions": [{"phase": "...", "text": "...", "competency_dimension": "...", "follow_up_strategy": "..."}]}

phase 可选值: introduction, project_deep_dive, tech_foundation
competency_dimension 可选值: tech_depth, project_experience, communication, role_fit"""


def _build_resume_prompt(position: str, resume_text: str) -> str:
    """Build the prompt for resume-driven question generation."""
    if position:
        position_hint = f"候选人目标岗位：{position}"
    else:
        position_hint = "请根据简历内容推断候选人最匹配的技术岗位方向"

    return f"""{position_hint}

候选人简历：
{resume_text[:2500]}

请仔细阅读以上简历，设计一套完全针对这位候选人背景的半结构化面试题目。

**要求**：
- 自我介绍环节（2题）：引导候选人介绍简历中的核心技术栈和关键项目，问题中要引用具体的项目名称和技术
- 项目深挖环节（3-4题）：逐一深挖简历中的每个主要项目，问具体的技术决策、架构取舍、量化结果、踩过的坑
- 技术基础环节（3-4题）：只考察简历中明确列出的技术栈的底层原理

**关键原则**：
- 每道题必须明确引用简历中的公司名、项目名、技术名词、数据指标
- 追问策略不是泛泛的"展开说说"，而是针对该题目的具体技术深挖点
- 让候选人感受到"面试官认真研读了简历的每一个细节"

返回严格 JSON（不要 markdown 标记）：
{{"questions": [{{"phase": "...", "text": "...", "competency_dimension": "...", "follow_up_strategy": "..."}}]}}

phase: introduction | project_deep_dive | tech_foundation
competency_dimension: tech_depth | project_experience | communication | role_fit"""


class PrepAgent:
    """Prep-phase agent responsible for building the interview plan."""

    def __init__(self):
        self._bank: dict = {}
        self._load_bank()

    def _load_bank(self):
        if _QUESTION_BANK_PATH.exists():
            with open(_QUESTION_BANK_PATH, "r", encoding="utf-8") as f:
                self._bank = json.load(f)
            logger.info("Question bank loaded: %d positions", len(self._bank))
        else:
            logger.warning("Question bank file not found: %s", _QUESTION_BANK_PATH)

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

        # A2 fix: In adaptive mode, skip expensive question-plan generation.
        # LiveAgent generates questions dynamically via the Evaluator→Interviewer loop.
        # We still generate a lightweight plan as fallback, but skip the 45s LLM call.
        if ctx.adaptive_mode:
            # Only build a minimal skeleton — LiveAgent won't use it
            ctx.question_plan = QuestionPlan(position=position)
            ctx.total_questions = 0  # Signal: adaptive mode, unknown count
        else:
            ctx.question_plan = await self._build_plan(position, resume_text)
            ctx.total_questions = len(ctx.question_plan.questions)

        return ctx

    # ── Internal ─────────────────────────────────────────

    def _build_profile(self, position: str, resume_text: Optional[str] = None) -> str:
        if resume_text:
            pos_info = f"目标方向: {position}" if position else "目标方向: 根据简历内容推断"
            return f"{pos_info}\n简历摘要: {resume_text[:200]}..."
        return f"目标方向: {position}" if position else "目标方向: 未指定"

    async def _summarise_resume(self, resume_text: str) -> str:
        """Use LLM to extract a concise summary from the resume."""
        if not has_real_llm():
            return f"简历内容({len(resume_text)}字): {resume_text[:300]}"
        try:
            prompt = f"请用100字以内总结这份简历的技术栈和核心经验:\n{resume_text[:2000]}"
            result = await llm_invoke(prompt, system_prompt="你是简历分析专家。简洁总结。")
            return result.strip()[:500]
        except Exception as e:
            logger.warning("Resume summary failed: %s", e)
            return resume_text[:500]

    async def _build_plan(
        self, position: str, resume_text: Optional[str] = None
    ) -> QuestionPlan:
        """Build the QuestionPlan.

        With resume: LLM generates questions entirely from resume content.
        Without resume: fall back to seed question bank.
        """
        plan = QuestionPlan(position=position)

        if resume_text and has_real_llm():
            # ── Resume-driven: LLM generates from scratch ──
            questions_data = await self._generate_from_resume(position, resume_text)
        else:
            # ── Fallback: seed question bank ──
            questions_data = self._load_from_bank(position)

        for q in questions_data:
            try:
                plan.questions.append(Question(
                    phase=PhaseEnum(q["phase"]),
                    text=q["text"],
                    competency_dimension=CompetencyDimension(q["competency_dimension"]),
                    follow_up_strategy=q.get("follow_up_strategy", ""),
                ))
            except (KeyError, ValueError) as e:
                logger.warning("Skipping invalid question: %s — %s", q, e)

        return plan

    # ── Resume-driven generation ──────────────────────────

    async def _generate_from_resume(
        self, position: str, resume_text: str
    ) -> list[dict]:
        """Let LLM generate interview questions entirely from the resume.

        Falls back to question bank on any failure.
        """
        import json as _json
        try:
            logger.info("Generating questions from resume for position '%s'...", position)
            result = await llm_invoke(
                _build_resume_prompt(position, resume_text),
                system_prompt=RESUME_DRIVEN_SYSTEM,
                timeout=BATCH_TIMEOUT,
            )
            # Parse JSON from LLM response
            result = result.strip()
            # Remove markdown code fences
            if result.startswith("```"):
                lines = result.split("\n")
                result = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            # Try to extract the first complete JSON object or array
            data = extract_json(result)
            questions = data.get("questions", data if isinstance(data, list) else [])
            if questions:
                logger.info("LLM generated %d resume-driven questions", len(questions))
                return questions
            else:
                logger.warning("LLM returned empty questions list")
        except Exception as e:
            logger.warning("Resume-driven generation failed: %s — falling back to bank", e)

        return self._load_from_bank(position)

    # ── Bank fallback ─────────────────────────────────────

    def _load_from_bank(self, position: str) -> list[dict]:
        """Load seed questions from the JSON bank. Used when no resume or LLM fails."""
        phase_map = {
            PhaseEnum.INTRODUCTION: "introduction",
            PhaseEnum.PROJECT_DEEP_DIVE: "project_deep_dive",
            PhaseEnum.TECH_FOUNDATION: "tech_foundation",
        }

        seed_questions = self._bank.get(position, {})
        if not seed_questions and position:
            logger.warning("No seed questions for '%s', falling back to 前端工程师", position)
            seed_questions = self._bank.get("前端工程师", {})
        elif not seed_questions:
            # Empty position — use the first available bank entry as fallback
            first_key = next(iter(self._bank.keys()), "前端工程师")
            logger.warning("Empty position, using first available bank entry: '%s'", first_key)
            seed_questions = self._bank.get(first_key, {})

        questions: list[dict] = []
        for phase, bank_key in phase_map.items():
            q_texts = seed_questions.get(bank_key, ["请说说你的理解。"])
            for i, text in enumerate(q_texts):
                dim = self._infer_dimension(phase, text, i)
                questions.append({
                    "phase": phase.value,
                    "text": text,
                    "competency_dimension": dim.value,
                    "follow_up_strategy": self._pick_follow_up_strategy(phase, dim),
                })

        logger.info("Loaded %d questions from bank for '%s'", len(questions), position)
        return questions

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
