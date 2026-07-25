"""Live Agent — manages the real-time interview conversation.

Behavioral rules (from our grilling session):
- Follow QuestionPlan order; allow ONE dynamic follow-up per question
- After a shallow answer, ask one clarifying follow-up; if still shallow, mark & skip
- Phase transition: content-driven, with hard time caps as safety net
- Total interview: ~20 min
- No interruption — wait for candidate to finish
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.models.interview import (
    AnswerRecord,
    CompetencyDimension,
    InterviewContext,
    InterviewStatus,
    PhaseEnum,
    Question,
    QuestionPlan,
    RoleEnum,
    Turn,
)
from app.services.llm_service import llm_invoke, has_real_llm

# Time budgets (seconds) — hard caps for each phase
PHASE_TIME_BUDGETS: dict[PhaseEnum, int] = {
    PhaseEnum.INTRODUCTION: 120,          # 2 min
    PhaseEnum.PROJECT_DEEP_DIVE: 480,     # 8 min
    PhaseEnum.TECH_FOUNDATION: 480,       # 8 min
    PhaseEnum.Q_AND_A: 120,               # 2 min
}

PHASE_ORDER: list[PhaseEnum] = [
    PhaseEnum.INTRODUCTION,
    PhaseEnum.PROJECT_DEEP_DIVE,
    PhaseEnum.TECH_FOUNDATION,
    PhaseEnum.Q_AND_A,
]

# Greetings for each phase
PHASE_GREETINGS: dict[PhaseEnum, str] = {
    PhaseEnum.INTRODUCTION:
        "你好！欢迎参加今天的模拟面试。先请你做一下自我介绍，让我了解一下你的背景和技术方向。",
    PhaseEnum.PROJECT_DEEP_DIVE:
        "好的，接下来我们深入聊聊你的项目经历。",
    PhaseEnum.TECH_FOUNDATION:
        "下面我们进入技术基础考察环节。我会问你一些技术底层原理的问题。",
    PhaseEnum.Q_AND_A:
        "面试的主要环节基本结束了。你有什么想问我的吗？可以问关于职位、团队、技术栈的任何问题。",
}


class LiveAgent:
    """Live-phase agent that drives the interview conversation."""

    def __init__(self):
        self._phase_start_time: dict[PhaseEnum, datetime] = {}

    # ── Public API ──────────────────────────────────────

    async def on_start(self, ctx: InterviewContext) -> Turn:
        """Called when the interview transitions to LIVE.
        Returns the first interviewer Turn.
        """
        ctx.status = InterviewStatus.LIVE
        ctx.current_phase = PhaseEnum.INTRODUCTION
        ctx.current_question_index = 0
        self._phase_start_time[PhaseEnum.INTRODUCTION] = datetime.now()

        return Turn(
            role=RoleEnum.INTERVIEWER,
            content=PHASE_GREETINGS[PhaseEnum.INTRODUCTION],
            phase=PhaseEnum.INTRODUCTION,
        )

    async def on_candidate_message(self, ctx: InterviewContext, content: str) -> Turn:
        """Called when the candidate sends a message during LIVE.
        Evaluates the answer, decides next action, returns interviewer Turn.
        """
        plan = ctx.question_plan
        if not plan or not plan.questions:
            return self._fallback_turn(ctx.current_phase)

        current_q = self._current_question(plan, ctx.current_question_index)

        # 1. Record the candidate's answer
        answer_record = await self._evaluate_answer(content, current_q)
        ctx.answer_records.append(answer_record)

        # Also record draft score on the question
        if current_q:
            current_q.draft_score = answer_record.draft_score

        # 2. Decide what to do next
        action = await self._decide_next_action(ctx, content, answer_record)

        # 3. Execute the action
        return await self._execute_action(ctx, action, current_q)

    # ── Answer evaluation ───────────────────────────────

    async def _evaluate_answer(self, content: str, question: Optional[Question]) -> AnswerRecord:
        """Evaluate a candidate answer into an AnswerRecord with draft score.

        Uses LLM when available; falls back to heuristic scoring.
        """
        if not question:
            return AnswerRecord(
                question_id="",
                question_text="",
                answer_summary=content[:100],
                dimension=CompetencyDimension.COMMUNICATION,
                draft_score=3,
                notes="",
            )

        if has_real_llm():
            return await self._llm_evaluate(content, question)
        return self._heuristic_evaluate(content, question)

    async def _llm_evaluate(self, content: str, question: Question) -> AnswerRecord:
        """Use LLM to evaluate answer quality."""
        prompt = (
            f"面试题目：{question.text}\n"
            f"考察维度：{question.competency_dimension.value}\n"
            f"候选人回答：{content}\n\n"
            f"请评估这个回答的质量，返回 JSON 格式：\n"
            f'{{"score": 1-5, "summary": "一句话摘要", "notes": "简短评价"}}\n'
            f"评分标准：1=完全不会, 2=基本不会, 3=基本掌握, 4=熟练掌握, 5=深度理解"
        )
        system = "你是专业的面试评估官。只返回 JSON，不要其他内容。"
        try:
            result = await llm_invoke(prompt, system_prompt=system)
            # Try to parse JSON from result
            import json
            # Extract JSON if wrapped in markdown
            if "```" in result:
                result = result.split("```")[1]
                if result.startswith("json"):
                    result = result[4:]
            data = json.loads(result.strip())
            return AnswerRecord(
                question_id=question.id,
                question_text=question.text,
                answer_summary=data.get("summary", content[:200]),
                dimension=question.competency_dimension,
                draft_score=int(data.get("score", 3)),
                notes=data.get("notes", ""),
            )
        except Exception:
            return self._heuristic_evaluate(content, question)

    def _heuristic_evaluate(self, content: str, question: Question) -> AnswerRecord:
        """Fallback heuristic scoring based on answer length."""
        length = len(content)
        score = 3
        if length < 20:
            score = 1
        elif length < 60:
            score = 2
        elif length > 300:
            score = 4
        elif length > 500:
            score = 5

        return AnswerRecord(
            question_id=question.id,
            question_text=question.text,
            answer_summary=content[:200],
            dimension=question.competency_dimension,
            draft_score=score,
            notes="",
        )

    # ── Decision engine ─────────────────────────────────

    async def _decide_next_action(
        self,
        ctx: InterviewContext,
        candidate_content: str,
        answer_record: AnswerRecord,
    ) -> dict:
        """Decide the next action: progress, follow-up, or transition phase."""
        plan = ctx.question_plan
        assert plan

        idx = ctx.current_question_index
        current_q = self._current_question(plan, idx)

        # ── Check for follow-up ─────────────────────────
        should_follow_up = self._should_follow_up(current_q, answer_record)
        if should_follow_up:
            return {"action": "follow_up", "question": current_q}

        # ── Move to next question in current phase ───────
        next_idx = self._next_question_in_phase(plan, idx, ctx.current_phase)
        if next_idx is not None:
            return {"action": "next_question", "index": next_idx}

        # ── Transition to next phase ─────────────────────
        next_phase = self._next_phase(ctx.current_phase)
        if next_phase is not None:
            first_idx = self._first_question_in_phase(plan, next_phase)
            return {
                "action": "transition_phase",
                "phase": next_phase,
                "index": first_idx if first_idx is not None else idx + 1,
            }

        # ── Interview is done ────────────────────────────
        return {"action": "done"}

    def _should_follow_up(self, question: Optional[Question], record: AnswerRecord) -> bool:
        """Determine if the candidate's answer warrants a follow-up."""
        if not question:
            return False
        if question.follow_up_asked:
            return False  # Already followed up once
        if record.draft_score and record.draft_score <= 2:
            return True  # Shallow answer → follow up
        return False

    def _next_question_in_phase(
        self, plan: QuestionPlan, current_idx: int, phase: PhaseEnum
    ) -> Optional[int]:
        """Find the next question in the same phase, or None if we should transition."""
        for i in range(current_idx + 1, len(plan.questions)):
            if plan.questions[i].phase == phase:
                return i
        return None

    def _first_question_in_phase(self, plan: QuestionPlan, phase: PhaseEnum) -> Optional[int]:
        """Find the first question for a given phase."""
        for i, q in enumerate(plan.questions):
            if q.phase == phase:
                return i
        return None

    def _next_phase(self, current: PhaseEnum) -> Optional[PhaseEnum]:
        """Return the next phase in order, or None if at the end."""
        try:
            idx = PHASE_ORDER.index(current)
            if idx + 1 < len(PHASE_ORDER):
                return PHASE_ORDER[idx + 1]
        except ValueError:
            pass
        return None

    # ── Action execution ────────────────────────────────

    async def _execute_action(
        self, ctx: InterviewContext, action: dict, current_q: Optional[Question]
    ) -> Turn:
        """Execute the decided action and return the interviewer Turn."""
        action_type = action["action"]

        if action_type == "follow_up":
            question = action["question"]
            question.follow_up_asked = True
            follow_up = await self._generate_follow_up(question)
            return Turn(
                role=RoleEnum.INTERVIEWER,
                content=follow_up,
                phase=ctx.current_phase,
                question_id=question.id,
            )

        elif action_type == "next_question":
            new_idx = action["index"]
            ctx.current_question_index = new_idx
            plan = ctx.question_plan
            assert plan
            q = plan.questions[new_idx]
            return Turn(
                role=RoleEnum.INTERVIEWER,
                content=q.text,
                phase=ctx.current_phase,
                question_id=q.id,
            )

        elif action_type == "transition_phase":
            new_phase = action["phase"]
            new_idx = action["index"]
            ctx.current_phase = new_phase
            ctx.current_question_index = new_idx
            self._phase_start_time[new_phase] = datetime.now()
            plan = ctx.question_plan
            assert plan

            greeting = PHASE_GREETINGS.get(new_phase, "")
            if new_idx < len(plan.questions):
                greeting += " " + plan.questions[new_idx].text

            return Turn(
                role=RoleEnum.INTERVIEWER,
                content=greeting,
                phase=new_phase,
            )

        elif action_type == "done":
            closing = "好的，面试到这里就结束了。感谢你的时间和精彩的回答！接下来我会为你生成一份评分报告。"
            return Turn(
                role=RoleEnum.INTERVIEWER,
                content=closing,
                phase=ctx.current_phase,
            )

        return self._fallback_turn(ctx.current_phase)

    # ── Follow-up generation ────────────────────────────

    async def _generate_follow_up(self, question: Question) -> str:
        """Generate a follow-up question. Uses LLM when available."""
        if has_real_llm():
            try:
                prompt = (
                    f"原始题目：{question.text}\n"
                    f"考察维度：{question.competency_dimension.value}\n"
                    f"追问策略：{question.follow_up_strategy}\n\n"
                    f"请生成一句自然的追问（中文），引导候选人更深入回答。只返回追问文本。"
                )
                result = await llm_invoke(prompt, system_prompt="你是专业的面试官。只返回追问，不要解释。")
                if result.strip():
                    return result.strip()
            except Exception:
                pass

        # Fallback canned follow-ups
        phase = question.phase
        if phase == PhaseEnum.PROJECT_DEEP_DIVE:
            return "你刚才提到了技术选型，能具体说一下当时还有什么备选方案，为什么最终选择了这个方案吗？"
        if phase == PhaseEnum.TECH_FOUNDATION:
            return "了解理论知识很好。能结合你实际项目中的例子，说说具体是怎么应用的吗？"
        return "能再具体展开说说吗？我想了解更多细节。"

    # ── Helpers ──────────────────────────────────────────

    def _current_question(self, plan: QuestionPlan, index: int) -> Optional[Question]:
        if 0 <= index < len(plan.questions):
            return plan.questions[index]
        return None

    def _fallback_turn(self, phase: PhaseEnum) -> Turn:
        return Turn(
            role=RoleEnum.INTERVIEWER,
            content="好的，请继续。",
            phase=phase,
        )
