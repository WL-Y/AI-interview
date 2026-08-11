"use client";

import { useInterviewStore } from "@/stores/interview";
import type { CompetencyDimension, AnswerRecord } from "@/stores/interview";

const DIMENSION_LABELS: Record<CompetencyDimension, string> = {
  tech_depth: "技术深度",
  project_experience: "项目经验",
  communication: "表达沟通",
  role_fit: "岗位匹配度",
};

const SCORE_LABELS = ["", "需大幅提升", "需要加强", "基本合格", "表现不错", "非常出色"];

function ScoreBar({ score, label }: { score: number; label: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-20 text-sm text-gray-600">{label}</span>
      <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
        <div
          className="h-full bg-brand-500 rounded-full transition-all duration-500"
          style={{ width: `${(score / 5) * 100}%` }}
        />
      </div>
      <span className="text-sm font-semibold text-gray-800 w-6 text-right">
        {score}/5
      </span>
    </div>
  );
}

function AnswerCard({ record }: { record: AnswerRecord }) {
  const score = record.draft_score || 3;
  return (
    <div className="border border-gray-100 rounded-lg p-3 space-y-2">
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs text-gray-500 flex-1 line-clamp-2">
          <span className="font-medium text-gray-700">Q: </span>
          {record.question_text}
        </p>
        <span className={`text-xs font-semibold px-2 py-0.5 rounded-full shrink-0
          ${score >= 4 ? "bg-green-50 text-green-700" : score >= 3 ? "bg-yellow-50 text-yellow-700" : "bg-red-50 text-red-700"}`}
        >
          {score}/5
        </span>
      </div>
      {record.notes && (
        <p className="text-xs text-gray-500 bg-gray-50 rounded p-2">
          💬 {record.notes}
        </p>
      )}
      {record.candidate_answer && (
        <details className="text-xs text-gray-400">
          <summary className="cursor-pointer hover:text-gray-500">查看回答</summary>
          <p className="mt-1 text-gray-500 bg-gray-50 rounded p-2 max-h-24 overflow-y-auto">
            {record.candidate_answer}
          </p>
        </details>
      )}
    </div>
  );
}

export function ReportScreen() {
  const session = useInterviewStore((s) => s.session);
  const setScreen = useInterviewStore((s) => s.setScreen);
  const setSession = useInterviewStore((s) => s.setSession);

  const handleRestart = () => {
    setSession(null as any);
    setScreen("landing");
  };

  if (!session?.scorecard) {
    return (
      <div className="interview-container items-center justify-center">
        <div className="text-center space-y-3">
          <div className="flex gap-1.5 justify-center">
            <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
            <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
            <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
          </div>
          <p className="text-gray-500 text-sm">正在生成评分报告...</p>
        </div>
      </div>
    );
  }

  const { scorecard } = session;
  const records: AnswerRecord[] = session.answer_records || [];

  return (
    <div className="interview-container gap-8 py-12 px-4">
      {/* Header */}
      <div className="text-center space-y-1">
        <h1 className="text-2xl font-bold">面试评分报告</h1>
        <p className="text-gray-500 text-sm">
          {session.candidate_profile?.split("\n")[0] || "模拟面试"}
        </p>
        <p className="text-gray-400 text-xs">
          用时 {session.elapsed_seconds ? `${Math.floor(session.elapsed_seconds / 60)}分${session.elapsed_seconds % 60}秒` : "—"} · 共 {records.length} 题
        </p>
      </div>

      {/* Overall score */}
      <div className="text-center">
        <div className="inline-flex items-center justify-center w-24 h-24 rounded-full bg-brand-50 text-brand-700">
          <span className="text-3xl font-bold">
            {scorecard.overall_score.toFixed(1)}
          </span>
        </div>
        <p className="text-sm text-gray-500 mt-2">综合评分</p>
      </div>

      {/* Dimension scores */}
      <div className="space-y-3">
        {scorecard.dimension_scores.map((ds) => (
          <ScoreBar
            key={ds.dimension}
            label={DIMENSION_LABELS[ds.dimension] ?? ds.dimension}
            score={ds.score}
          />
        ))}
      </div>

      {/* Strengths & Weaknesses */}
      <div className="grid grid-cols-2 gap-6">
        <div className="space-y-2">
          <h3 className="font-semibold text-green-700">✅ 亮点</h3>
          <ul className="list-disc list-inside text-sm text-gray-600 space-y-1">
            {scorecard.strengths.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </div>
        <div className="space-y-2">
          <h3 className="font-semibold text-orange-700">🔧 待改进</h3>
          <ul className="list-disc list-inside text-sm text-gray-600 space-y-1">
            {scorecard.weaknesses.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      </div>

      {/* Improvement plan */}
      {scorecard.improvement_plan && (
        <div className="bg-gray-50 rounded-xl p-5 space-y-2">
          <h3 className="font-semibold text-gray-800">📋 改进建议</h3>
          <p className="text-sm text-gray-600 whitespace-pre-wrap">
            {scorecard.improvement_plan}
          </p>
        </div>
      )}

      {/* ── Per-question breakdown ── */}
      {records.length > 0 && (
        <div className="space-y-3">
          <h3 className="font-semibold text-gray-800">📝 逐题回顾</h3>
          <div className="space-y-2">
            {records.map((r, i) => (
              <AnswerCard key={r.question_id || i} record={r} />
            ))}
          </div>
        </div>
      )}

      {/* Restart */}
      <button
        onClick={handleRestart}
        className="w-full py-3 bg-gray-800 text-white rounded-xl font-medium
                   hover:bg-gray-900 transition-colors"
      >
        再来一次
      </button>
    </div>
  );
}
