"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import { useInterviewStore } from "@/stores/interview";

const PHASE_LABELS: Record<string, string> = {
  introduction: "📝 自我介绍",
  project_deep_dive: "🔍 项目深挖",
  tech_foundation: "💡 技术基础",
  q_and_a: "🙋 反问环节",
};

const PHASE_ORDER = ["introduction", "project_deep_dive", "tech_foundation", "q_and_a"];

const SCORE_EMOJI: Record<number, string> = {
  1: "😰", 2: "😅", 3: "🙂", 4: "👍", 5: "🌟",
};

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function InterviewScreen() {
  const session = useInterviewStore((s) => s.session);
  const textInput = useInterviewStore((s) => s.textInput);
  const setTextInput = useInterviewStore((s) => s.setTextInput);
  const sendMessage = useInterviewStore((s) => s.sendMessage);
  const sendVoice = useInterviewStore((s) => s.sendVoice);
  const finishInterview = useInterviewStore((s) => s.finishInterview);
  const pauseInterview = useInterviewStore((s) => s.pauseInterview);
  const resumeInterview = useInterviewStore((s) => s.resumeInterview);
  const isLoading = useInterviewStore((s) => s.isLoading);
  const voiceMode = useInterviewStore((s) => s.voiceMode);
  const toggleVoiceMode = useInterviewStore((s) => s.toggleVoiceMode);
  const isRecording = useInterviewStore((s) => s.isRecording);
  const setIsRecording = useInterviewStore((s) => s.setIsRecording);
  const lastAudioBase64 = useInterviewStore((s) => s.lastAudioBase64);
  const setLastAudioBase64 = useInterviewStore((s) => s.setLastAudioBase64);
  const lastDraftScore = useInterviewStore((s) => s.lastDraftScore);
  const lastFeedback = useInterviewStore((s) => s.lastFeedback);
  const showFeedback = useInterviewStore((s) => s.showFeedback);
  const dismissFeedback = useInterviewStore((s) => s.dismissFeedback);
  const progress = useInterviewStore((s) => s.progress);
  const fetchProgress = useInterviewStore((s) => s.fetchProgress);

  const bottomRef = useRef<HTMLDivElement>(null);
  const recognitionRef = useRef<any>(null);
  const [elapsed, setElapsed] = useState(0);

  // ── Elapsed time ticker ──────────────────────────────
  useEffect(() => {
    if (session?.status !== "live") return;
    setElapsed(session.elapsed_seconds || 0);
    const timer = setInterval(() => {
      setElapsed((prev) => prev + 1);
    }, 1000);
    return () => clearInterval(timer);
  }, [session?.status, session?.elapsed_seconds]);

  // B2 fix: Poll progress every 3s so adaptive UI (coverage%, topic) stays live
  useEffect(() => {
    if (session?.status !== "live") return;
    fetchProgress();
    const timer = setInterval(fetchProgress, 3000);
    return () => clearInterval(timer);
  }, [session?.status, fetchProgress]);

  // Auto-scroll to latest message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [session?.transcript]);

  // Play audio when received
  useEffect(() => {
    if (lastAudioBase64) {
      const audio = new Audio(`data:audio/wav;base64,${lastAudioBase64}`);
      audio.play().catch(() => {});
      setLastAudioBase64(null);
    }
  }, [lastAudioBase64, setLastAudioBase64]);

  // ── Web Speech API (browser STT) ─────────────────────

  const startRecording = useCallback(() => {
    const SpeechRecognition =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      alert("你的浏览器不支持语音识别，请使用 Chrome 或切换到文字模式");
      return;
    }

    const rec = new SpeechRecognition();
    rec.lang = "zh-CN";
    rec.interimResults = false;
    rec.continuous = false;
    recognitionRef.current = rec;

    rec.onstart = () => setIsRecording(true);
    rec.onend = () => setIsRecording(false);

    rec.onresult = async (event: any) => {
      const transcript = event.results[0][0].transcript;
      if (!transcript.trim() || !session) return;

      if (voiceMode) {
        await sendVoice(session.session_id, transcript);
      } else {
        await sendMessage(transcript);
      }
    };

    rec.onerror = (event: any) => {
      setIsRecording(false);
      if (event.error !== "aborted") {
        console.error("Speech recognition error:", event.error);
      }
    };

    rec.start();
  }, [session, voiceMode, sendVoice, sendMessage, setIsRecording]);

  const stopRecording = useCallback(() => {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
    }
    setIsRecording(false);
  }, [setIsRecording]);

  // ── Handlers ──────────────────────────────────────────

  const handleSend = () => {
    if (!textInput.trim()) return;
    sendMessage(textInput.trim());
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const isPaused = session?.status === "paused";

  // ── Progress calculations ─────────────────────────────

  const totalQ = session?.total_questions || 0;
  const answeredQ = session?.answered_questions || 0;
  const currentPhase = session?.current_phase || "introduction";
  const currentPhaseIdx = PHASE_ORDER.indexOf(currentPhase);

  // Adaptive mode: use coverage %, fall back to question-based %
  const isAdaptive = progress?.adaptive_mode !== false;
  const coveragePct = progress?.coverage_pct || 0;
  const currentTopic = progress?.current_topic || "";

  const progressPercent = isAdaptive
    ? coveragePct
    : totalQ > 0 ? Math.round((answeredQ / totalQ) * 100) : 0;

  // ── Render ────────────────────────────────────────────

  return (
    <div className="interview-container px-4">
      {/* ── Header bar: phase + progress + controls ── */}
      <div className="flex flex-col gap-2 py-3 border-b mb-3">
        {/* Top row: phase label + time + controls */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-sm font-medium text-brand-700 bg-brand-50 px-3 py-1 rounded-full">
              {PHASE_LABELS[currentPhase] || currentPhase}
            </span>
            {/* Phase progress dots */}
            <div className="hidden sm:flex items-center gap-1">
              {PHASE_ORDER.map((p, i) => (
                <div
                  key={p}
                  className={`w-2 h-2 rounded-full transition-colors ${
                    i < currentPhaseIdx
                      ? "bg-green-400"
                      : i === currentPhaseIdx
                        ? "bg-brand-500"
                        : "bg-gray-200"
                  }`}
                />
              ))}
            </div>
          </div>
          <div className="flex items-center gap-3">
            {/* Elapsed time */}
            <span className="text-xs text-gray-400 font-mono">{formatTime(elapsed)}</span>

            {/* Pause / Resume */}
            {isPaused ? (
              <button
                onClick={resumeInterview}
                className="text-xs px-2 py-1 rounded-full bg-green-50 border border-green-300 text-green-700 hover:bg-green-100 transition-colors"
              >
                ▶ 继续面试
              </button>
            ) : (
              <button
                onClick={pauseInterview}
                className="text-xs px-2 py-1 rounded-full bg-yellow-50 border border-yellow-300 text-yellow-700 hover:bg-yellow-100 transition-colors"
              >
                ⏸ 暂停
              </button>
            )}

            {/* Voice toggle */}
            <button
              onClick={toggleVoiceMode}
              className={`text-xs px-2 py-1 rounded-full border transition-colors
                ${voiceMode
                  ? "bg-green-50 border-green-300 text-green-700"
                  : "bg-gray-50 border-gray-200 text-gray-500"
                }`}
            >
              {voiceMode ? "🎤" : "⌨️"}
            </button>

            {/* End interview */}
            <button
              onClick={finishInterview}
              className="text-sm text-gray-400 hover:text-red-500 transition-colors"
            >
              结束
            </button>
          </div>
        </div>

        {/* Progress bar */}
        <div className="flex items-center gap-2">
          <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-brand-500 rounded-full transition-all duration-500"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
          <span className="text-xs text-gray-400 font-mono">
            {isAdaptive
              ? `${coveragePct}%`
              : `${answeredQ}/${totalQ}`
            }
          </span>
          {isAdaptive && currentTopic && (
            <span className="text-xs text-brand-500 bg-brand-50 px-1.5 py-0.5 rounded-full max-w-[120px] truncate" title={currentTopic}>
              {currentTopic}
            </span>
          )}
        </div>
      </div>

      {/* ── Paused overlay ── */}
      {isPaused && (
        <div className="flex items-center justify-center py-8">
          <div className="text-center space-y-3">
            <span className="text-4xl">⏸️</span>
            <p className="text-gray-500 text-sm">面试已暂停</p>
            <p className="text-gray-400 text-xs">
              已用 {formatTime(elapsed)} · {isAdaptive
                ? `技能覆盖 ${coveragePct}%`
                : `已完成 ${answeredQ}/${totalQ} 题`
              }
            </p>
            <button
              onClick={resumeInterview}
              className="px-6 py-2 bg-brand-600 text-white rounded-xl font-medium text-sm
                         hover:bg-brand-700 transition-colors"
            >
              继续面试
            </button>
          </div>
        </div>
      )}

      {/* ── Messages ── */}
      {!isPaused && (
        <div className="flex-1 overflow-y-auto space-y-4 pb-4">
          {session?.transcript.map((turn, i) => (
            <div
              key={i}
              className={`flex ${turn.role === "candidate" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed
                  ${turn.role === "candidate"
                    ? "bg-brand-600 text-white rounded-br-md"
                    : turn.role === "system"
                      ? "bg-yellow-50 text-yellow-800 border border-yellow-200 rounded-bl-md"
                      : "bg-gray-100 text-gray-800 rounded-bl-md"
                  }`}
              >
                {turn.content}
              </div>
            </div>
          ))}

          {/* Loading / Recording indicator */}
          {(isLoading || isRecording) && (
            <div className="flex justify-start">
              <div className="bg-gray-100 rounded-2xl rounded-bl-md px-4 py-3">
                {isRecording ? (
                  <div className="flex items-center gap-2 text-red-500 text-sm">
                    <span className="relative flex h-3 w-3">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />
                      <span className="relative inline-flex rounded-full h-3 w-3 bg-red-500" />
                    </span>
                    正在聆听...
                  </div>
                ) : (
                  <div className="flex items-center gap-2 text-sm text-gray-500">
                    <div className="flex gap-1">
                      <span className="w-1.5 h-1.5 bg-brand-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                      <span className="w-1.5 h-1.5 bg-brand-400 rounded-full animate-bounce" style={{ animationDelay: "120ms" }} />
                      <span className="w-1.5 h-1.5 bg-brand-400 rounded-full animate-bounce" style={{ animationDelay: "240ms" }} />
                    </div>
                    AI 正在分析你的回答...
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ── Per-question feedback toast ── */}
          {showFeedback && lastDraftScore && (
            <div className="flex justify-center">
              <div className="flex items-center gap-3 bg-white border border-gray-200 rounded-xl px-4 py-3 shadow-sm max-w-sm">
                <span className="text-2xl">{SCORE_EMOJI[lastDraftScore] || "🤔"}</span>
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-gray-700">
                      本题评分: {lastDraftScore}/5
                    </span>
                    <span className="text-xs text-gray-400">
                      {["", "需大幅提升", "需要加强", "基本合格", "表现不错", "非常出色"][lastDraftScore]}
                    </span>
                  </div>
                  {lastFeedback && (
                    <p className="text-xs text-gray-500 mt-0.5">{lastFeedback}</p>
                  )}
                </div>
                <button
                  onClick={dismissFeedback}
                  className="text-gray-300 hover:text-gray-500 text-lg leading-none"
                >
                  ×
                </button>
              </div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>
      )}

      {/* ── Input area ── */}
      {!isPaused && (
        <div className="border-t pt-4 flex gap-3">
          {voiceMode ? (
            <button
              onClick={isRecording ? stopRecording : startRecording}
              className={`flex-1 py-4 rounded-xl font-medium text-sm transition-all
                ${isRecording
                  ? "bg-red-50 border-2 border-red-400 text-red-600"
                  : "bg-brand-600 text-white hover:bg-brand-700"
                } disabled:opacity-50 disabled:cursor-not-allowed`}
              disabled={isLoading}
            >
              {isRecording ? "⏹ 停止录音" : "🎤 点击开始回答"}
            </button>
          ) : (
            <>
              <textarea
                value={textInput}
                onChange={(e) => setTextInput(e.target.value)}
                onKeyDown={handleKeyDown}
                rows={2}
                className="flex-1 border border-gray-200 rounded-xl px-4 py-3 text-sm resize-none
                           focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent"
                placeholder="输入你的回答...（Shift+Enter 换行，Enter 发送）"
              />
              <button
                onClick={handleSend}
                disabled={isLoading || !textInput.trim()}
                className="self-end px-6 py-3 bg-brand-600 text-white rounded-xl font-medium
                           hover:bg-brand-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                发送
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
