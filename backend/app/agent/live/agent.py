"""Adaptive Live Agent — manages the real-time interview conversation.

Architecture (per adaptive_interview_agent.md §1, §16):
    Candidate Answer
         ↓
    Evaluator Call (LLM) → structured assessment
         ↓
    Update AdaptiveState (skill scores, confidence, coverage)
         ↓
    Interviewer Call (LLM) → next question, dynamically generated
         ↓
    Next Question

Core principles:
- Interviewer asks, Evaluator judges — NEVER the same agent doing both (§1)
- Information Gain drives question selection, not a pre-made list (§2)
- Score and Confidence are separate — low confidence = need more evidence (§9)
- Priority(skill) = Importance × Uncertainty × RemainingCoverage (§10)
- One question at a time, adapt based on answer quality (§2)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from app.agent.live.evaluator import EvaluatorAgent
from app.models.interview import (
    AdaptiveState,
    AnswerRecord,
    CompetencyDimension,
    EvalAction,
    EvaluatorOutput,
    InterviewContext,
    InterviewStatus,
    PhaseEnum,
    RoleEnum,
    SkillEstimate,
    Turn,
    UnderstandingType,
)
from app.services.llm_service import llm_invoke, has_real_llm

logger = logging.getLogger(__name__)

# Time budgets (seconds) — hard caps for each phase
PHASE_TIME_BUDGETS: dict[PhaseEnum, int] = {
    PhaseEnum.INTRODUCTION: 120,
    PhaseEnum.PROJECT_DEEP_DIVE: 480,
    PhaseEnum.TECH_FOUNDATION: 480,
    PhaseEnum.Q_AND_A: 120,
}

PHASE_ORDER: list[PhaseEnum] = [
    PhaseEnum.INTRODUCTION,
    PhaseEnum.PROJECT_DEEP_DIVE,
    PhaseEnum.TECH_FOUNDATION,
    PhaseEnum.Q_AND_A,
]

PHASE_COVERAGE_THRESHOLD = 0.75

PHASE_GREETINGS: dict[PhaseEnum, str] = {
    PhaseEnum.INTRODUCTION:
        "你好！欢迎参加今天的模拟面试。先请你做一下自我介绍，让我了解一下你的背景和技术方向。",
    PhaseEnum.PROJECT_DEEP_DIVE:
        "好的，接下来我们深入聊聊你的项目经历。",
    PhaseEnum.TECH_FOUNDATION:
        "下面我们进入技术基础考察环节，我会针对你简历中的技术栈问一些底层原理的问题。",
    PhaseEnum.Q_AND_A:
        "面试的主要环节基本结束了。你有什么想问我的吗？可以问关于职位、团队、技术栈的任何问题。",
}

# ── Interviewer system prompt (condensed from doc §2) ─────

INTERVIEWER_SYSTEM = """# Role: Adaptive Technical Interviewer

You are a senior technical interviewer conducting a live interview.

## Core Objective
Every question should maximize your understanding of the candidate's TRUE ability.
Pursue **Information Gain**, not question count. Ask where uncertainty is highest.

## Behavior Rules
- Professional, natural, restrained — do NOT teach or lecture
- Do NOT praise frequently or reveal internal scores/state
- Do NOT expose evaluator analysis or show question lists
- Ask ONE question per turn — do NOT stack multiple questions

## Adaptive Questioning — Follow the Evaluator's Recommendation

### DEEPEN (answer was strong):
Probe deeper — ask about mechanism ("Why does that work?"), counterexamples
("When would this fail?"), trade-offs ("What did you give up?"), or scale
("What if data is 100x larger?").

### CLARIFY (answer was vague):
Stay on topic, ask for specifics — "Can you walk me through a concrete example?",
"What exactly happens at the {specific} layer?", "Under what conditions does this hold?"

### CHALLENGE (seems memorized):
Test real understanding — change an assumption ("What if we remove X?"),
ask for derivation ("Prove this from first principles."), construct a counterexample,
or transfer to a different context.

### HINT (candidate is close):
Give ONE small hint and re-ask. Don't give away the full answer.

### EASIER (too difficult):
Reduce difficulty. Ask a more foundational question on the same topic.

### ADVANCE (enough evidence here):
Move to the next most uncertain skill area. Transition naturally.

### VERIFY_EXPERIENCE:
Drill into personal contribution — "What specifically did YOU implement?",
"What was the hardest bug YOU debugged?", "Walk me through YOUR code structure."

## Question Types
- Concept: foundational understanding
- Mechanism: WHY something works
- Counterexample: boundary understanding
- Debugging: symptom → diagnosis
- Scenario: real engineering problem
- Design: open system design
- Drill-down: verify project experience depth

## Project Deep-Dive
Focus on: personal contribution (not "we"), technical decisions and trade-offs,
hard problems solved, measurable results (how measured?), failures learned from.

## Difficulty Adaptation
Target the candidate's ability BOUNDARY — hard enough to be informative,
not so hard they can only say "I don't know".
- Consistently strong → increase difficulty
- Struggling → decrease difficulty

## Phase Awareness
- INTRODUCTION: Brief, 1-2 questions to understand background
- PROJECT_DEEP_DIVE: Drill into each major project, verify authenticity
- TECH_FOUNDATION: Test depth of tech stack knowledge from resume
- Q_AND_A: Let candidate ask questions, answer briefly

## Output Format
Return ONLY the next question text in Chinese. No JSON, no markup, no explanation.
If the interview should end, output exactly: <<END_INTERVIEW>>"""


class LiveAgent:
    """Adaptive live-phase agent.

    Uses the Evaluator → State → Interviewer loop (doc §7).
    Each turn: evaluate answer → update skills → generate next question.
    """

    def __init__(self):
        self._evaluator = EvaluatorAgent()
        # B5 fix: per-session dicts to avoid singleton state leak across sessions
        self._phase_start_time: dict[str, dict[PhaseEnum, datetime]] = {}
        self._phase_answer_count: dict[str, dict[PhaseEnum, int]] = {}
        self._total_paused_seconds: dict[str, float] = {}

    # ── Public API ──────────────────────────────────────

    async def on_start(self, ctx: InterviewContext) -> Turn:
        """Initialise adaptive state and return the first interviewer Turn."""
        ctx.status = InterviewStatus.LIVE
        ctx.current_phase = PhaseEnum.INTRODUCTION
        ctx.current_question_index = 0
        ctx.answered_questions = 0
        ctx.elapsed_seconds = 0
        ctx.paused_at = None
        self._phase_start_time.setdefault(ctx.session_id, {})[PhaseEnum.INTRODUCTION] = datetime.now()
        self._phase_answer_count.setdefault(ctx.session_id, {})[PhaseEnum.INTRODUCTION] = 0
        self._total_paused_seconds[ctx.session_id] = 0.0

        # Init adaptive state from resume/profile
        ctx.adaptive_state = self._init_adaptive_state(ctx)

        # Personalised opening with LLM
        greeting = PHASE_GREETINGS[PhaseEnum.INTRODUCTION]
        if has_real_llm() and ctx.candidate_profile:
            try:
                custom = await self._generate_opening(ctx)
                if custom:
                    greeting = custom
            except Exception:
                pass

        return Turn(
            role=RoleEnum.INTERVIEWER,
            content=greeting,
            phase=PhaseEnum.INTRODUCTION,
        )

    async def on_candidate_message(self, ctx: InterviewContext, content: str) -> Turn:
        """Core adaptive loop (doc §7):
        1. Evaluate answer via Evaluator agent
        2. Update adaptive state with skill estimates
        3. Generate next question via Interviewer LLM
        """
        current_question_text = self._last_question_text(ctx)

        # ── 1. Evaluate ──────────────────────────────────
        previous_qs = self._recent_question_texts(ctx, n=3)
        evaluation = await self._evaluator.evaluate(
            question_text=current_question_text,
            candidate_answer=content,
            candidate_profile=ctx.candidate_profile,
            adaptive_state=ctx.adaptive_state,
            previous_questions=previous_qs,
        )
        ctx.last_evaluation = evaluation

        # Record answer
        answer_record = self._build_answer_record(
            current_question_text, content, evaluation, ctx.current_phase
        )
        ctx.answer_records.append(answer_record)
        ctx.answered_questions += 1

        # B6 fix: increment per-phase answer counter
        phase_counts = self._phase_answer_count.setdefault(ctx.session_id, {})
        phase_counts[ctx.current_phase] = phase_counts.get(ctx.current_phase, 0) + 1

        # B7 fix: subtract paused duration from elapsed time
        if ctx.created_at:
            paused = self._total_paused_seconds.get(ctx.session_id, 0.0)
            ctx.elapsed_seconds = int((datetime.now() - ctx.created_at).total_seconds() - paused)

        # ── 2. Update adaptive state ─────────────────────
        if ctx.adaptive_state:
            self._update_adaptive_state(ctx.adaptive_state, evaluation)

        # ── 3. Check phase transition / end ──────────────
        phase_action = self._check_phase_transition(ctx)

        if phase_action == "end_interview":
            closing = "好的，面试到这里就结束了。感谢你的时间和精彩的回答！接下来我会为你生成一份评分报告。"
            return Turn(role=RoleEnum.INTERVIEWER, content=closing, phase=ctx.current_phase)

        if phase_action == "transition":
            ctx = await self._transition_phase(ctx)

        # ── 4. Generate next question ────────────────────
        next_question = await self._generate_next_question(ctx, evaluation)

        if "<<END_INTERVIEW>>" in next_question:
            closing = "好的，面试到这里就结束了。感谢你的时间和精彩的回答！接下来我会为你生成一份评分报告。"
            return Turn(role=RoleEnum.INTERVIEWER, content=closing, phase=ctx.current_phase)

        ctx.current_question_index += 1
        return Turn(
            role=RoleEnum.INTERVIEWER,
            content=next_question,
            phase=ctx.current_phase,
        )

    # ── Pause / Resume ───────────────────────────────────

    def pause(self, ctx: InterviewContext):
        if ctx.status != InterviewStatus.LIVE:
            raise ValueError("只有进行中的面试才能暂停")
        ctx.status = InterviewStatus.PAUSED
        ctx.paused_at = datetime.now()

    def resume(self, ctx: InterviewContext) -> Turn:
        if ctx.status != InterviewStatus.PAUSED:
            raise ValueError("只有暂停中的面试才能恢复")

        # B7 fix: accumulate paused duration
        if ctx.paused_at:
            pause_duration = (datetime.now() - ctx.paused_at).total_seconds()
            self._total_paused_seconds[ctx.session_id] = \
                self._total_paused_seconds.get(ctx.session_id, 0.0) + pause_duration

        ctx.status = InterviewStatus.LIVE
        ctx.paused_at = None

        elapsed_min = ctx.elapsed_seconds // 60
        state_summary = ""
        if ctx.adaptive_state and ctx.adaptive_state.skills:
            covered = sum(1 for s in ctx.adaptive_state.skills.values() if s.confidence >= 0.5)
            total = len(ctx.adaptive_state.skills)
            state_summary = f" | 已评估技能: {covered}/{total}"

        return Turn(
            role=RoleEnum.SYSTEM,
            content=f"面试已恢复（已用 {elapsed_min} 分钟，已回答 {ctx.answered_questions} 题{state_summary}）。我们继续吧！",
            phase=ctx.current_phase,
        )

    # ── Progress ─────────────────────────────────────────

    def get_progress(self, ctx: InterviewContext) -> dict:
        coverage_pct = 0.0
        if ctx.adaptive_state and ctx.adaptive_state.coverage:
            vals = ctx.adaptive_state.coverage.values()
            coverage_pct = round((sum(vals) / len(vals)) * 100) if vals else 0

        skills_summary = {}
        if ctx.adaptive_state:
            for name, skill in ctx.adaptive_state.skills.items():
                skills_summary[name] = {
                    "score": skill.score,
                    "confidence": round(skill.confidence, 2),
                    "evidence_count": skill.evidence_count,
                }

        return {
            "current_phase": ctx.current_phase.value,
            "current_question_index": ctx.current_question_index,
            "total_questions": ctx.total_questions,
            "answered_questions": ctx.answered_questions,
            "elapsed_seconds": ctx.elapsed_seconds,
            "status": ctx.status.value,
            "phase_order": [p.value for p in PHASE_ORDER],
            "current_phase_label": _phase_label(ctx.current_phase),
            "coverage_pct": coverage_pct,
            "adaptive_mode": ctx.adaptive_mode,
            "skills": skills_summary,
            "current_topic": ctx.adaptive_state.current_topic if ctx.adaptive_state else "",
            "latest_draft_score": (
                ctx.answer_records[-1].draft_score if ctx.answer_records else None
            ),
            "latest_feedback": (
                ctx.answer_records[-1].notes if ctx.answer_records else ""
            ),
        }

    # ── Adaptive State ───────────────────────────────────

    def _init_adaptive_state(self, ctx: InterviewContext) -> AdaptiveState:
        """Extract tech keywords from profile to create skill dimensions."""
        state = AdaptiveState()
        profile = (ctx.candidate_profile + " " + ctx.jd_summary).lower()

        skill_patterns = {
            "java": ["java", "spring", "jvm", "maven", "gradle", "hibernate", "mybatis"],
            "python": ["python", "django", "flask", "fastapi", "pytorch", "tensorflow", "pandas"],
            "javascript": ["javascript", "js", "node", "react", "vue", "angular", "typescript", "前端"],
            "golang": ["golang", "go", "gin", "goroutine"],
            "database": ["sql", "mysql", "postgresql", "mongodb", "redis", "索引", "事务"],
            "system_design": ["架构", "微服务", "分布式", "高并发", "高可用", "扩容", "限流", "熔断"],
            "coding": ["算法", "数据结构", "leetcode", "代码"],
            "networking": ["http", "tcp", "网络", "rpc", "rest", "api"],
            "os": ["linux", "内存", "进程", "线程", "并发", "锁"],
            "cloud": ["aws", "docker", "kubernetes", "k8s", "ci/cd", "devops", "云"],
        }

        for skill_name, keywords in skill_patterns.items():
            if any(kw in profile for kw in keywords):
                keyword_hits = sum(1 for kw in keywords if kw in profile)
                importance = min(0.9, 0.4 + keyword_hits * 0.1)
                state.skills[skill_name] = SkillEstimate(
                    score=50, confidence=0.1, evidence_count=0, importance=importance,
                )
                state.coverage[skill_name] = 0.0

        # Always add communication and project_experience
        for name, imp in [("communication", 0.5), ("project_experience", 0.7)]:
            if name not in state.skills:
                state.skills[name] = SkillEstimate(
                    score=60 if name == "communication" else 50,
                    confidence=0.1, evidence_count=0, importance=imp,
                )
                state.coverage[name] = 0.0

        logger.info("Adaptive state init: %d skills %s", len(state.skills), list(state.skills.keys()))
        return state

    def _update_adaptive_state(self, state: AdaptiveState, evaluation: EvaluatorOutput):
        """Apply evaluator's skill_updates with smoothing (doc §8).
        new = old * (1-α) + observed * α, where α ∝ evidence_strength.
        """
        alpha_base = 0.15
        has_strong = len(evaluation.strong_evidence) > 0

        for skill_name, update in evaluation.skill_updates.items():
            alpha = alpha_base * (1.5 if has_strong else 1.0)

            if skill_name in state.skills:
                current = state.skills[skill_name]
                new_score = int(current.score * (1 - alpha) + update.score * alpha)
                new_conf = min(1.0, round(current.confidence * (1 - alpha * 0.7) + update.confidence * alpha * 0.7, 2))
                state.skills[skill_name] = SkillEstimate(
                    score=new_score, confidence=new_conf,
                    evidence_count=current.evidence_count + 1,
                    importance=current.importance,
                )
                state.coverage[skill_name] = min(1.0, state.coverage.get(skill_name, 0.0) + 0.15)
            else:
                state.skills[skill_name] = update
                state.coverage[skill_name] = 0.2

        # Track current topic
        if evaluation.skill_updates:
            best = max(evaluation.skill_updates.items(), key=lambda x: x[1].confidence, default=None)
            if best and best[0] != state.current_topic:
                state.current_topic = best[0]
                state.turns_on_topic = 1
                state.hints_given = 0
            else:
                state.turns_on_topic += 1
        else:
            state.turns_on_topic += 1

        # Adapt difficulty
        avg_score = (evaluation.correctness + evaluation.depth + evaluation.reasoning) / 3.0
        if avg_score >= 3.5 and state.current_difficulty < 5:
            state.current_difficulty += 1
        elif avg_score <= 1.0 and state.current_difficulty > 1:
            state.current_difficulty -= 1

    # ── Interviewer LLM ──────────────────────────────────

    async def _generate_next_question(
        self, ctx: InterviewContext, evaluation: EvaluatorOutput
    ) -> str:
        """Generate next question via Interviewer LLM. Falls back to canned questions."""
        if not has_real_llm():
            return self._fallback_question(ctx, evaluation)

        try:
            prompt = self._build_interviewer_prompt(ctx, evaluation)
            result = await llm_invoke(prompt, system_prompt=INTERVIEWER_SYSTEM, timeout=25.0)
            if result and result.strip():
                return result.strip()
        except Exception as e:
            logger.warning("Interviewer LLM failed: %s", e)

        return self._fallback_question(ctx, evaluation)

    async def _generate_opening(self, ctx: InterviewContext) -> str:
        """Generate a personalised opening greeting."""
        prompt = (
            f"候选人背景：{ctx.candidate_profile[:600]}\n\n"
            f"生成一句自然的面试开场白（中文），提到候选人的主要技术方向，让候选人做自我介绍。"
            f"不超过两句话。只返回开场白文本。"
        )
        try:
            result = await llm_invoke(prompt, system_prompt="你是专业面试官。只返回开场白。", timeout=15.0)
            if result and result.strip():
                return result.strip()
        except Exception:
            pass
        return ""

    def _build_interviewer_prompt(
        self, ctx: InterviewContext, evaluation: EvaluatorOutput
    ) -> str:
        parts = []

        # Candidate context
        parts.append(f"## Candidate Background\n{ctx.candidate_profile[:800]}\n")

        # Current phase
        parts.append(f"## Phase: {_phase_label(ctx.current_phase)} ({ctx.current_phase.value})")
        parts.append(f"Question #{ctx.answered_questions + 1} in this phase\n")

        # Adaptive state — rank by importance × uncertainty
        if ctx.adaptive_state and ctx.adaptive_state.skills:
            parts.append("## Skill Estimates (score | confidence | importance)")
            ranked = sorted(
                ctx.adaptive_state.skills.items(),
                key=lambda x: x[1].importance * (1 - x[1].confidence),
                reverse=True,
            )
            for name, skill in ranked[:8]:
                bar = "█" * int(skill.confidence * 10) + "░" * (10 - int(skill.confidence * 10))
                parts.append(
                    f"- {name}: {skill.score} | {bar} {skill.confidence:.1f} "
                    f"| imp={skill.importance:.1f} | n={skill.evidence_count}"
                )
            if ranked:
                top = ranked[0]
                parts.append(f"\n❗ Priority target: **{top[0]}** "
                             f"(importance={top[1].importance:.1f}, uncertainty={1-top[1].confidence:.1f})\n")

        # Current state
        if ctx.adaptive_state:
            parts.append(f"Current topic: {ctx.adaptive_state.current_topic or 'none'}")
            parts.append(f"Turns on topic: {ctx.adaptive_state.turns_on_topic}/{ctx.adaptive_state.max_turns_per_topic}")
            parts.append(f"Difficulty: {ctx.adaptive_state.current_difficulty}/5")
            parts.append(f"Hints: {ctx.adaptive_state.hints_given}")

        # Coverage snapshot
        if ctx.adaptive_state and ctx.adaptive_state.coverage:
            covered = [k for k, v in ctx.adaptive_state.coverage.items() if v >= PHASE_COVERAGE_THRESHOLD]
            uncovered = [k for k, v in ctx.adaptive_state.coverage.items() if v < PHASE_COVERAGE_THRESHOLD]
            if covered:
                parts.append(f"✅ Covered: {', '.join(covered)}")
            if uncovered:
                parts.append(f"⏳ Needs work: {', '.join(uncovered)}")

        # Recent transcript
        if ctx.transcript:
            parts.append("\n## Recent Conversation")
            for turn in ctx.transcript[-4:]:
                tag = "🎤 Candidate" if turn.role == RoleEnum.CANDIDATE else "👔 Interviewer"
                parts.append(f"{tag}: {turn.content[:200]}")

        # Evaluator's recommendation
        parts.append(f"""
## Evaluator Assessment (HIDDEN — use for decisions, don't expose)
- Understanding: {evaluation.understanding_type.value}
- Correctness={evaluation.correctness}/4 Depth={evaluation.depth}/4 Reasoning={evaluation.reasoning}/4
- Practicality={evaluation.practicality}/4 Communication={evaluation.communication}/4
- Gap: {evaluation.detected_gap or 'none'}
- Strong evidence: {len(evaluation.strong_evidence)} items
- Problematic: {len(evaluation.problematic_evidence)} items

## Action: **{evaluation.recommended_action.value}**
## Probe: {evaluation.recommended_probe or 'Advance to most uncertain skill'}

---
Generate the NEXT question (Chinese, ONE question only).
Follow the recommended action. Do NOT reveal evaluator internals.
Output <<END_INTERVIEW>> if the interview should conclude.""")
        return "\n".join(parts)

    # ── Phase Management ─────────────────────────────────

    def _check_phase_transition(self, ctx: InterviewContext) -> str:
        """Returns "stay" | "transition" | "end_interview"."""
        if not ctx.adaptive_state:
            return "stay"

        state = ctx.adaptive_state

        if ctx.current_phase == PhaseEnum.Q_AND_A and state.turns_on_topic >= 2:
            return "end_interview"

        # Time budget check (per-session)
        session_phases = self._phase_start_time.get(ctx.session_id, {})
        if ctx.current_phase in session_phases:
            elapsed = (datetime.now() - session_phases[ctx.current_phase]).total_seconds()
            if elapsed > PHASE_TIME_BUDGETS.get(ctx.current_phase, 480):
                return "end_interview" if self._next_phase(ctx.current_phase) is None else "transition"

        if self._should_end_phase(ctx):
            return "end_interview" if self._next_phase(ctx.current_phase) is None else "transition"

        return "stay"

    def _should_end_phase(self, ctx: InterviewContext) -> bool:
        if not ctx.adaptive_state:
            return ctx.answered_questions >= 3

        if ctx.current_phase == PhaseEnum.Q_AND_A:
            return ctx.adaptive_state.turns_on_topic >= 3

        relevant = self._phase_skills(ctx.current_phase)
        if not relevant:
            return ctx.adaptive_state.turns_on_topic >= 4

        covered = all(
            ctx.adaptive_state.coverage.get(s, 0.0) >= PHASE_COVERAGE_THRESHOLD
            for s in relevant
        )

        max_turns = {"introduction": 3, "project_deep_dive": 6, "tech_foundation": 6, "q_and_a": 3}
        # B6 fix: per-phase answer count, not global answered_questions
        phase_answers = self._phase_answer_count.get(ctx.session_id, {}).get(ctx.current_phase, 0)
        too_many = phase_answers >= max_turns.get(ctx.current_phase.value, 5)

        return covered or too_many

    async def _transition_phase(self, ctx: InterviewContext) -> InterviewContext:
        next_p = self._next_phase(ctx.current_phase)
        if next_p is None:
            return ctx

        old = ctx.current_phase
        ctx.current_phase = next_p
        self._phase_start_time.setdefault(ctx.session_id, {})[next_p] = datetime.now()
        self._phase_answer_count.setdefault(ctx.session_id, {})[next_p] = 0

        if ctx.adaptive_state:
            ctx.adaptive_state.turns_on_topic = 0
            ctx.adaptive_state.current_topic = ""
            ctx.adaptive_state.hints_given = 0
            ctx.adaptive_state.phase_topics_covered.append(old.value)

        greeting = PHASE_GREETINGS.get(next_p, "")
        if greeting:
            ctx.transcript.append(Turn(role=RoleEnum.INTERVIEWER, content=greeting, phase=next_p))

        logger.info("Phase: %s → %s", old, next_p)
        return ctx

    def _phase_skills(self, phase: PhaseEnum) -> list[str]:
        mapping = {
            PhaseEnum.INTRODUCTION: ["communication"],
            PhaseEnum.PROJECT_DEEP_DIVE: ["project_experience", "system_design"],
            PhaseEnum.TECH_FOUNDATION: [],
            PhaseEnum.Q_AND_A: ["communication"],
        }
        return mapping.get(phase, [])

    def _next_phase(self, current: PhaseEnum) -> Optional[PhaseEnum]:
        try:
            idx = PHASE_ORDER.index(current)
            return PHASE_ORDER[idx + 1] if idx + 1 < len(PHASE_ORDER) else None
        except ValueError:
            return None

    # ── Helpers ──────────────────────────────────────────

    def _last_question_text(self, ctx: InterviewContext) -> str:
        for turn in reversed(ctx.transcript):
            if turn.role == RoleEnum.INTERVIEWER:
                return turn.content
        return ""

    def _recent_question_texts(self, ctx: InterviewContext, n: int = 3) -> list[str]:
        qs = [t.content for t in reversed(ctx.transcript) if t.role == RoleEnum.INTERVIEWER]
        return list(reversed(qs[:n]))

    def _build_answer_record(
        self, question_text: str, answer: str, evaluation: EvaluatorOutput, phase: PhaseEnum
    ) -> AnswerRecord:
        # Map 0-4 evaluator scores → 1-5 draft score
        avg = (evaluation.correctness + evaluation.depth + evaluation.reasoning) / 3.0
        draft_score = max(1, min(5, round(avg + 1)))

        # B1 fix: infer competency dimension from the current interview phase,
        # not hardcoded to tech_depth. Tech foundation → tech_depth,
        # project deep-dive → project_experience, intro/Q&A → communication.
        if phase == PhaseEnum.TECH_FOUNDATION:
            dimension = CompetencyDimension.TECH_DEPTH
        elif phase == PhaseEnum.PROJECT_DEEP_DIVE:
            dimension = CompetencyDimension.PROJECT_EXPERIENCE
        elif phase in (PhaseEnum.INTRODUCTION, PhaseEnum.Q_AND_A):
            dimension = CompetencyDimension.COMMUNICATION
        else:
            dimension = CompetencyDimension.ROLE_FIT

        # A1 fix: do NOT leak evaluator internals (detected_gap, evidence)
        # to the candidate-facing frontend. Keep only a brief score summary.
        score_labels = {1: "需大幅提升", 2: "需要加强", 3: "基本合格", 4: "表现不错", 5: "非常出色"}
        notes = f"评分: {draft_score}/5 ({score_labels.get(draft_score, '')})"

        return AnswerRecord(
            question_id="",
            question_text=question_text[:200],
            answer_summary=answer[:200],
            dimension=dimension,
            draft_score=draft_score,
            notes=notes,
            candidate_answer=answer,
        )

    # ── Fallback ─────────────────────────────────────────

    def _fallback_question(self, ctx: InterviewContext, evaluation: EvaluatorOutput) -> str:
        action = evaluation.recommended_action
        phase = ctx.current_phase
        topic = ctx.adaptive_state.current_topic if ctx.adaptive_state else ""

        if action == EvalAction.CLARIFY:
            return "能再具体展开说说吗？我想了解更多实现细节。"
        if action == EvalAction.DEEPEN:
            return "你讲的这个方案，在什么情况下可能会出问题？它的最大局限性是什么？"
        if action == EvalAction.CHALLENGE:
            return "如果把一个关键条件改一下，这个结论还成立吗？能推导一下吗？"
        if action == EvalAction.EASIER:
            return "没关系，我们先从基础开始——能说说这个技术最基本的工作原理吗？"
        if action == EvalAction.VERIFY_EXPERIENCE:
            return "在这个项目里，你个人具体负责了哪些模块的开发和设计？"

        if phase == PhaseEnum.INTRODUCTION:
            return "你的技术栈主要是哪些？最擅长的技术方向是什么？"
        if phase == PhaseEnum.PROJECT_DEEP_DIVE:
            return "能详细说说你做的项目中，技术选型的主要考量是什么吗？"
        if phase == PhaseEnum.TECH_FOUNDATION:
            return f"能深入讲讲{topic or '你熟悉的技术'}的底层实现原理吗？"
        if phase == PhaseEnum.Q_AND_A:
            return "你还有什么想了解的？关于团队、技术栈、或者职业发展都可以问。"

        return "好的，请继续。"


def _phase_label(phase: PhaseEnum) -> str:
    labels = {
        PhaseEnum.INTRODUCTION: "自我介绍",
        PhaseEnum.PROJECT_DEEP_DIVE: "项目深挖",
        PhaseEnum.TECH_FOUNDATION: "技术基础",
        PhaseEnum.Q_AND_A: "反问环节",
    }
    return labels.get(phase, phase.value)
