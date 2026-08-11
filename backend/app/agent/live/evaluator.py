"""Evaluator Agent — hidden evaluator that judges candidate answers.

Per the adaptive interview agent design (adaptive_interview_agent.md §3):
- Evaluator is a HIDDEN agent — candidates never see its analysis
- It evaluates evidence, not confidence — fluent ≠ correct
- It detects understanding types, extracts evidence, finds knowledge gaps
- It recommends the next action for the Interviewer
- Score and Confidence are always separate (§9)

Input: question text, candidate answer, resume/profile context, current adaptive state
Output: structured EvaluatorOutput (JSON)
"""

from __future__ import annotations

import json as _json
import logging
from typing import Optional

from app.models.interview import (
    AdaptiveState,
    EvalAction,
    EvaluatorOutput,
    SkillEstimate,
    UnderstandingType,
)
from app.services.llm_service import llm_invoke, has_real_llm
from app.services.json_utils import extract_json

logger = logging.getLogger(__name__)

# ── Evaluator system prompt (condensed from doc §3) ───────────

EVALUATOR_SYSTEM = """# Role: Interview Evaluator (Hidden)

You are a hidden technical interview evaluator. You do NOT talk to the candidate.
Your job is to evaluate each answer objectively and update the interview state.

## Core Principle
**Evaluate evidence, not confidence.**
- Fluent delivery ≠ correct answer
- Poor expression ≠ poor understanding
- Judge only by the reasoning and evidence in the answer

## Step 1: Identify Expected Knowledge
What does this question truly test? Identify the core concept, expected reasoning,
important assumptions, and common misconceptions.

## Step 2: Score Each Dimension (0-4)

- **correctness**: 0=fundamentally wrong, 1=mostly wrong, 2=partially correct, 3=correct, 4=correct with precise boundaries
- **depth**: 0=no understanding, 1=terminology only, 2=basic mechanism, 3=strong mechanism, 4=first-principles / expert
- **reasoning**: 0=baseless guessing, 1=weak, 2=reasonable, 3=logically strong, 4=rigorous and transferable
- **practicality**: 0=unrealistic, 1=textbook only, 2=some engineering awareness, 3=practical, 4=strong production judgment
- **communication**: 0=incomprehensible, 1=very unclear, 2=understandable, 3=clear, 4=concise and structured

## Step 3: Detect Understanding Type
Classify as one of:
- genuine_understanding — truly understands
- partial_understanding — understands some parts
- memorized_answer — textbook/rote answer, no real depth
- lucky_guess — happened to be right
- misconception — fundamentally wrong understanding
- insufficient_evidence — not enough to judge

## Step 4: Extract Evidence
- **strong_evidence**: what truly proves the candidate's ability
- **weak_evidence**: may be correct but insufficient to prove understanding
- **problematic_evidence**: errors, contradictions, important omissions

## Step 5: Detect Knowledge Gap
Find the SINGLE most important gap worth probing next.
Focus on the most critical gap, not a laundry list.

## Step 6: Estimate Skill Updates
For each relevant skill, provide:
- skill name (lowercase, underscore-separated, e.g. "database", "java", "system_design")
- new_score (0-100)
- new_confidence (0-1)
Be conservative — one answer shouldn't change a score by more than ±15 points.
Confidence should increase more when evidence is strong.

## Step 7: Recommend Next Action
Pick ONE action:
- DEEPEN — good answer, probe deeper into mechanism/edge-cases
- CLARIFY — vague answer, ask for concrete specifics
- CHALLENGE — seems memorized, test with counterexample/derivation
- HINT — candidate is close, give small hint then re-ask
- EASIER — clearly too difficult for candidate
- ADVANCE — enough evidence on this topic, move to next skill
- VERIFY_EXPERIENCE — project claims unclear, verify personal contribution
- END — sufficient evidence collected overall

## Step 8: Recommended Probe
Give the Interviewer specific direction for the next question.
Describe what to ask about, not the exact question wording.
Focus on the detected gap.

## Anti-Bias Rules
Do NOT raise scores based on: fancy terminology, confident tone, prestigious school/company names, impressive-sounding project names, candidate claiming "I know this well".
Do NOT lower technical scores just because communication is poor — score communication separately.

## Output Format
Return ONLY valid JSON (no markdown, no explanation):
{
  "correctness": 2,
  "depth": 1,
  "reasoning": 2,
  "practicality": 1,
  "communication": 3,
  "understanding_type": "partial_understanding",
  "strong_evidence": ["..."],
  "weak_evidence": ["..."],
  "problematic_evidence": [],
  "detected_gap": "...",
  "skill_updates": {
    "database": {"score": 62, "confidence": 0.45, "evidence_count": 2, "importance": 0.8}
  },
  "recommended_action": "CLARIFY",
  "recommended_probe": "Ask how the candidate would determine which specific layer caused the latency."
}"""


class EvaluatorAgent:
    """Hidden evaluator that assesses each candidate answer and updates state."""

    # Default skill importance weights (fallback when resume doesn't specify)
    DEFAULT_SKILLS = {
        "coding": 0.7,
        "system_design": 0.7,
        "database": 0.6,
        "networking": 0.5,
        "os": 0.4,
        "communication": 0.6,
        "project_experience": 0.7,
    }

    async def evaluate(
        self,
        question_text: str,
        candidate_answer: str,
        candidate_profile: str,
        adaptive_state: Optional[AdaptiveState],
        previous_questions: list[str] = [],
    ) -> EvaluatorOutput:
        """Evaluate a candidate's answer and return structured assessment.

        Args:
            question_text: The question that was asked
            candidate_answer: The candidate's response
            candidate_profile: Resume summary / candidate background
            adaptive_state: Current interview state (skills, coverage, etc.)
            previous_questions: Recently asked questions (for context)
        """
        if not has_real_llm():
            return self._heuristic_evaluate(question_text, candidate_answer, adaptive_state)

        try:
            prompt = self._build_prompt(
                question_text, candidate_answer, candidate_profile,
                adaptive_state, previous_questions,
            )
            result = await llm_invoke(prompt, system_prompt=EVALUATOR_SYSTEM, timeout=20.0)
            return self._parse_result(result, adaptive_state)
        except Exception as e:
            logger.warning("Evaluator LLM call failed: %s — falling back to heuristic", e)
            return self._heuristic_evaluate(question_text, candidate_answer, adaptive_state)

    # ── Prompt building ───────────────────────────────────

    def _build_prompt(
        self,
        question_text: str,
        candidate_answer: str,
        candidate_profile: str,
        adaptive_state: Optional[AdaptiveState],
        previous_questions: list[str],
    ) -> str:
        parts = []

        if candidate_profile:
            parts.append(f"## Candidate Background\n{candidate_profile[:800]}\n")

        parts.append(f"## Current Question\n{question_text}\n")
        parts.append(f"## Candidate Answer\n{candidate_answer}\n")

        if previous_questions:
            parts.append(f"## Recent Questions\n" + "\n".join(f"- {q}" for q in previous_questions[-3:]) + "\n")

        if adaptive_state and adaptive_state.skills:
            parts.append("## Current Skill Estimates")
            for name, skill in adaptive_state.skills.items():
                conf_label = "★" if skill.confidence >= 0.7 else "?" if skill.confidence < 0.3 else "~"
                parts.append(
                    f"- {name}: score={skill.score} confidence={skill.confidence:.2f} {conf_label} "
                    f"(evidence={skill.evidence_count})"
                )
            parts.append("")

        if adaptive_state and adaptive_state.current_topic:
            parts.append(f"Current topic: {adaptive_state.current_topic} (turn {adaptive_state.turns_on_topic}/{adaptive_state.max_turns_per_topic})")
            parts.append(f"Current difficulty: {adaptive_state.current_difficulty}/5\n")

        parts.append("Evaluate this answer and return JSON per the system instructions.")
        return "\n".join(parts)

    # ── JSON parsing ──────────────────────────────────────

    def _parse_result(self, raw: str, state: Optional[AdaptiveState]) -> EvaluatorOutput:
        """Parse LLM output into EvaluatorOutput. Falls back to heuristic on parse failure."""
        # Strip markdown fences
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        try:
            data = _json.loads(text)
        except _json.JSONDecodeError:
            # Try to extract first complete JSON object (shared utility)
            data = extract_json(text)

        if not data or not isinstance(data, dict):
            logger.warning("Evaluator returned unparseable output: %s", raw[:200])
            return self._heuristic_evaluate("", "", state)

        # ── Build EvaluatorOutput ─────────────────────────
        try:
            ut = data.get("understanding_type", "insufficient_evidence")
            if ut not in UnderstandingType._value2member_map_:
                ut = "insufficient_evidence"

            action = data.get("recommended_action", "ADVANCE")
            if action not in EvalAction._value2member_map_:
                action = "ADVANCE"

            # Parse skill updates
            skill_updates: dict[str, SkillEstimate] = {}
            raw_updates = data.get("skill_updates", {})
            if isinstance(raw_updates, dict):
                for name, val in raw_updates.items():
                    if isinstance(val, dict):
                        skill_updates[name] = SkillEstimate(
                            score=max(0, min(100, int(val.get("score", 50)))),
                            confidence=max(0.0, min(1.0, float(val.get("confidence", 0.1)))),
                            evidence_count=max(0, int(val.get("evidence_count", 1))),
                            importance=float(val.get("importance", 0.5)),
                        )

            return EvaluatorOutput(
                correctness=max(0, min(4, int(data.get("correctness", 0)))),
                depth=max(0, min(4, int(data.get("depth", 0)))),
                reasoning=max(0, min(4, int(data.get("reasoning", 0)))),
                practicality=max(0, min(4, int(data.get("practicality", 0)))),
                communication=max(0, min(4, int(data.get("communication", 0)))),
                understanding_type=UnderstandingType(ut),
                strong_evidence=data.get("strong_evidence", []) or [],
                weak_evidence=data.get("weak_evidence", []) or [],
                problematic_evidence=data.get("problematic_evidence", []) or [],
                detected_gap=str(data.get("detected_gap", "")),
                skill_updates=skill_updates,
                recommended_action=EvalAction(action),
                recommended_probe=str(data.get("recommended_probe", "")),
            )
        except Exception as e:
            logger.warning("Failed to build EvaluatorOutput: %s", e)
            return self._heuristic_evaluate("", "", state)

    # ── Heuristic fallback ────────────────────────────────

    def _heuristic_evaluate(
        self,
        question_text: str,
        candidate_answer: str,
        state: Optional[AdaptiveState],
    ) -> EvaluatorOutput:
        """Fast heuristic evaluation when LLM is unavailable."""
        length = len(candidate_answer)

        # Rough scoring from length + keyword indicators
        if length < 20:
            correctness, depth, reasoning, practicality, communication = 0, 0, 0, 0, 1
            ut = UnderstandingType.INSUFFICIENT
        elif length < 60:
            correctness, depth, reasoning, practicality, communication = 1, 1, 1, 0, 2
            ut = UnderstandingType.INSUFFICIENT
        elif length < 150:
            correctness, depth, reasoning, practicality, communication = 2, 2, 2, 1, 3
            ut = UnderstandingType.PARTIAL
        elif length < 400:
            correctness, depth, reasoning, practicality, communication = 3, 2, 2, 2, 3
            ut = UnderstandingType.PARTIAL
        else:
            correctness, depth, reasoning, practicality, communication = 3, 3, 3, 2, 4
            ut = UnderstandingType.GENUINE

        # Detect likely memorization (very long but generic)
        generic_phrases = ["众所周知", "一般来说", "在计算机科学中", "根据定义"]
        generic_count = sum(1 for p in generic_phrases if p in candidate_answer)
        if length > 200 and generic_count >= 2:
            ut = UnderstandingType.MEMORIZED

        # Build skill updates (heuristic: map answer quality to generic skills)
        avg_score = (correctness + depth + reasoning) / 3.0
        mapped_score = int(avg_score / 4.0 * 100)

        skill_updates: dict[str, SkillEstimate] = {}
        if state and state.current_topic:
            skill_updates[state.current_topic] = SkillEstimate(
                score=mapped_score,
                confidence=0.3 + (length / 1000) * 0.3,  # Longer answer → slightly more confidence
                evidence_count=1,
                importance=0.6,
            )

        # Determine action
        if length < 20:
            action = EvalAction.CLARIFY
            probe = "Candidate gave very short answer — ask for more detail"
        elif ut == UnderstandingType.MEMORIZED:
            action = EvalAction.CHALLENGE
            probe = "Answer sounds memorized — ask for a concrete example or counterexample"
        elif length > 400:
            action = EvalAction.DEEPEN
            probe = "Good detailed answer — probe deeper into edge cases or trade-offs"
        else:
            action = EvalAction.ADVANCE
            probe = "Move to next topic"

        return EvaluatorOutput(
            correctness=correctness,
            depth=depth,
            reasoning=reasoning,
            practicality=practicality,
            communication=communication,
            understanding_type=ut,
            strong_evidence=[f"Answer length: {length} chars"] if length > 200 else [],
            weak_evidence=[f"Answer length: {length} chars"] if length <= 200 else [],
            problematic_evidence=[],
            detected_gap="Need more detailed answer" if length < 150 else "",
            skill_updates=skill_updates,
            recommended_action=action,
            recommended_probe=probe,
        )


