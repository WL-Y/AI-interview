"""Post Agent — evaluates the full interview and generates a ScoreCard.

Scoring model (from our grilling session):
- 4 dimensions × 5-point scale
- Per-question draft scores → aggregate into dimension scores
- Generate strengths, weaknesses, and improvement plan

In M1 (Mock), uses heuristic aggregation from answer records.
In M3 (Real LLM), will use LLM to evaluate transcript quality.
"""

from __future__ import annotations

from collections import defaultdict

from app.models.interview import (
    AnswerRecord,
    CompetencyDimension,
    DimensionScore,
    InterviewContext,
    InterviewStatus,
    RoleEnum,
    ScoreCard,
)
from app.services.llm_service import llm_invoke, has_real_llm

POST_SCORING_SYSTEM = """你是一个资深的面试评估专家。根据完整的面试对话记录，
为候选人从以下四个维度评分（1-5分）：
- tech_depth（技术深度）
- project_experience（项目经验）
- communication（表达沟通）
- role_fit（岗位匹配度）

对每个维度给出分数、评价。然后列出 2-3 个亮点和 2-3 个待改进点，以及改进建议。

只返回 JSON，格式：
{
  "overall_score": 3.5,
  "dimension_scores": [
    {"dimension": "tech_depth", "score": 4, "comment": "..."},
    ...
  ],
  "strengths": ["..."],
  "weaknesses": ["..."],
  "improvement_plan": "..."
}"""


class PostAgent:
    """Post-phase agent that evaluates the interview and produces a ScoreCard."""

    # ── Public API ──────────────────────────────────────

    async def run(self, ctx: InterviewContext) -> InterviewContext:
        """Evaluate the completed interview and populate the ScoreCard."""
        if not ctx.answer_records and not ctx.transcript:
            return ctx

        if has_real_llm():
            await self._llm_evaluate(ctx)
        else:
            self._heuristic_evaluate(ctx)

        ctx.status = InterviewStatus.POST
        return ctx

    # ── LLM evaluation ───────────────────────────────────

    async def _llm_evaluate(self, ctx: InterviewContext):
        """Use LLM to evaluate the full transcript."""
        # Build transcript summary
        lines = []
        for turn in ctx.transcript:
            role = "面试官" if turn.role == RoleEnum.INTERVIEWER else "候选人"
            lines.append(f"{role}: {turn.content}")
        transcript_text = "\n".join(lines[-50:])  # Last 50 turns max

        prompt = (
            f"候选人方向：{ctx.candidate_profile}\n"
            f"岗位JD摘要：{ctx.jd_summary or '无'}\n\n"
            f"面试对话记录：\n{transcript_text}\n\n"
            f"请评估这场面试，返回 JSON。"
        )

        try:
            result = await llm_invoke(prompt, system_prompt=POST_SCORING_SYSTEM)
            # Parse JSON
            import json
            if "```" in result:
                result = result.split("```")[1]
                if result.startswith("json"):
                    result = result[4:]
            data = json.loads(result.strip())

            dim_scores = []
            for ds in data.get("dimension_scores", []):
                dim_val = ds.get("dimension", "")
                try:
                    dim = CompetencyDimension(dim_val)
                except ValueError:
                    continue
                dim_scores.append(DimensionScore(
                    dimension=dim,
                    score=int(ds.get("score", 3)),
                    comment=ds.get("comment", ""),
                ))

            ctx.scorecard = ScoreCard(
                overall_score=float(data.get("overall_score", 3.0)),
                dimension_scores=dim_scores,
                strengths=data.get("strengths", []),
                weaknesses=data.get("weaknesses", []),
                improvement_plan=data.get("improvement_plan", ""),
            )
        except Exception:
            self._heuristic_evaluate(ctx)

    # ── Heuristic evaluation (fallback) ──────────────────

    def _heuristic_evaluate(self, ctx: InterviewContext):
        """Fallback heuristic scoring."""
        dimension_scores = self._aggregate_scores(ctx.answer_records)
        overall = self._compute_overall(dimension_scores)
        strengths, weaknesses = self._identify_highlights(dimension_scores)
        improvement_plan = self._generate_improvement_plan(
            dimension_scores, strengths, weaknesses
        )
        ctx.scorecard = ScoreCard(
            overall_score=overall,
            dimension_scores=dimension_scores,
            strengths=strengths,
            weaknesses=weaknesses,
            improvement_plan=improvement_plan,
        )

    # ── Internal ─────────────────────────────────────────

    def _aggregate_scores(
        self, records: list[AnswerRecord]
    ) -> list[DimensionScore]:
        """Aggregate per-question draft scores into per-dimension scores."""
        # Group by dimension
        by_dim: dict[CompetencyDimension, list[int]] = defaultdict(list)
        for r in records:
            if r.draft_score is not None:
                by_dim[r.dimension].append(r.draft_score)

        results: list[DimensionScore] = []
        for dim in CompetencyDimension:
            scores = by_dim.get(dim, [])
            if scores:
                avg = round(sum(scores) / len(scores))
            else:
                avg = 3  # default if no questions in this dimension

            results.append(DimensionScore(
                dimension=dim,
                score=avg,
                comment=self._dimension_comment(dim, avg),
            ))
        return results

    def _dimension_comment(self, dim: CompetencyDimension, score: int) -> str:
        """Generate a canned comment for a dimension score."""
        comments = {
            CompetencyDimension.TECH_DEPTH: {
                5: "技术功底扎实，能深入讲解底层原理。",
                4: "技术基础较好，大部分问题回答到位。",
                3: "技术基础达到基本要求，部分深度问题可加强。",
                2: "技术基础有待提升，建议系统梳理核心知识点。",
                1: "技术基础薄弱，建议从基础原理开始系统学习。",
            },
            CompetencyDimension.PROJECT_EXPERIENCE: {
                5: "项目经验丰富，能清晰表达技术选型和架构决策。",
                4: "项目经验良好，有一定的架构思考能力。",
                3: "项目经验中等，可以加强对技术决策的思考。",
                2: "项目经验有限，建议在真实项目中多承担核心角色。",
                1: "缺乏有深度的项目经验，建议从参与开源项目入手。",
            },
            CompetencyDimension.COMMUNICATION: {
                5: "表达清晰流畅，逻辑严密，沟通能力出色。",
                4: "表达较清晰，大部分问题回答有条理。",
                3: "表达能力基本过关，偶有表达不清晰的情况。",
                2: "表达有时不够清晰，建议多练习结构化表达（如 STAR 方法）。",
                1: "表达需要大幅提升，回答较为碎片化。",
            },
            CompetencyDimension.ROLE_FIT: {
                5: "与目标岗位高度匹配，技术栈和项目经验非常契合。",
                4: "与目标岗位较为匹配，部分方面可加强。",
                3: "基本匹配岗位要求，有一定提升空间。",
                2: "与岗位要求有一定差距，建议补充相关技术栈经验。",
                1: "与目标岗位匹配度较低，建议重新评估职位方向。",
            },
        }
        return comments.get(dim, {}).get(score, "")

    def _compute_overall(self, dimension_scores: list[DimensionScore]) -> float:
        """Compute weighted overall score."""
        weights = {
            CompetencyDimension.TECH_DEPTH: 0.30,
            CompetencyDimension.PROJECT_EXPERIENCE: 0.30,
            CompetencyDimension.COMMUNICATION: 0.20,
            CompetencyDimension.ROLE_FIT: 0.20,
        }
        total = 0.0
        total_weight = 0.0
        for ds in dimension_scores:
            w = weights.get(ds.dimension, 0.25)
            total += ds.score * w
            total_weight += w
        if total_weight > 0:
            return round(total / total_weight, 1)
        return 3.0

    def _identify_highlights(
        self, dimension_scores: list[DimensionScore]
    ) -> tuple[list[str], list[str]]:
        """Extract strengths (score ≥ 4) and weaknesses (score ≤ 2)."""
        strengths: list[str] = []
        weaknesses: list[str] = []

        for ds in dimension_scores:
            if ds.score >= 4:
                strengths.append(f"{self._dim_label(ds.dimension)}: {ds.comment}")
            elif ds.score <= 2:
                weaknesses.append(f"{self._dim_label(ds.dimension)}: {ds.comment}")

        return strengths, weaknesses

    def _dim_label(self, dim: CompetencyDimension) -> str:
        labels = {
            CompetencyDimension.TECH_DEPTH: "技术深度",
            CompetencyDimension.PROJECT_EXPERIENCE: "项目经验",
            CompetencyDimension.COMMUNICATION: "表达沟通",
            CompetencyDimension.ROLE_FIT: "岗位匹配度",
        }
        return labels.get(dim, dim.value)

    def _generate_improvement_plan(
        self,
        dimension_scores: list[DimensionScore],
        strengths: list[str],
        weaknesses: list[str],
    ) -> str:
        """Generate an improvement plan based on the score profile."""
        lines = []

        if weaknesses:
            lines.append("📌 重点关注：")
            for w in weaknesses:
                lines.append(f"  • {w}")
            lines.append("")

        lines.append("📚 建议行动：")
        low_dims = [ds for ds in dimension_scores if ds.score <= 3]
        for ds in low_dims:
            if ds.dimension == CompetencyDimension.TECH_DEPTH:
                lines.append("  • 每周刷 3-5 道 LeetCode + 阅读技术核心书籍（如 JS 高级程序设计/CSAPP）")
            elif ds.dimension == CompetencyDimension.PROJECT_EXPERIENCE:
                lines.append("  • 主导一个 side project，完整经历从方案设计到上线的过程")
            elif ds.dimension == CompetencyDimension.COMMUNICATION:
                lines.append("  • 练习 STAR 方法（Situation-Task-Action-Result）结构化表达")
            elif ds.dimension == CompetencyDimension.ROLE_FIT:
                lines.append("  • 对比目标岗位 JD，制定技能补齐计划，补充关键技术栈的实际使用经验")

        if not low_dims:
            lines.append("  • 你的整体表现不错！建议定期模拟面试，保持面试手感。")

        return "\n".join(lines)
