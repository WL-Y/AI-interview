"use client";

import { useEffect, useRef, useCallback } from "react";
import { useInterviewStore } from "@/stores/interview";

const PHASE_LABELS: Record<string, string> = {
  introduction: "📝 自我介绍",
  project_deep_dive: "🔍 项目深挖",
  tech_foundation: "💡 技术基础",
  q_and_a: "🙋 反问环节",
};

export function InterviewScreen() {
  const session = useInterviewStore((s) => s.session);
  const textInput = useInterviewStore((s) => s.textInput);
  const setTextInput = useInterviewStore((s) => s.setTextInput);
  const sendMessage = useInterviewStore((s) => s.sendMessage);
  const sendVoice = useInterviewStore((s) => s.sendVoice);
  const finishInterview = useInterviewStore((s) => s.finishInterview);
  const isLoading = useInterviewStore((s) => s.isLoading);
  const voiceMode = useInterviewStore((s) => s.voiceMode);
  const toggleVoiceMode = useInterviewStore((s) => s.toggleVoiceMode);
  const isRecording = useInterviewStore((s) => s.isRecording);
  const setIsRecording = useInterviewStore((s) => s.setIsRecording);
  const lastAudioBase64 = useInterviewStore((s) => s.lastAudioBase64);
  const setLastAudioBase64 = useInterviewStore((s) => s.setLastAudioBase64);

  const bottomRef = useRef<HTMLDivElement>(null);
  const recognitionRef = useRef<any>(null);

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

  // ── Render ────────────────────────────────────────────

  return (
    <div className="interview-container px-4">
      {/* Header: phase indicator + voice toggle */}
      <div className="flex items-center justify-between py-4 border-b mb-4">
        <div className="text-sm font-medium text-brand-700 bg-brand-50 px-3 py-1 rounded-full">
          {PHASE_LABELS[session?.current_phase ?? "introduction"]}
        </div>
        <div className="flex items-center gap-3">
          {/* Voice mode toggle */}
          <button
            onClick={toggleVoiceMode}
            className={`text-xs px-2 py-1 rounded-full border transition-colors
              ${voiceMode
                ? "bg-green-50 border-green-300 text-green-700"
                : "bg-gray-50 border-gray-200 text-gray-500"
              }`}
          >
            {voiceMode ? "🎤 语音模式" : "⌨️ 文字模式"}
          </button>
          <button
            onClick={finishInterview}
            className="text-sm text-gray-400 hover:text-red-500 transition-colors"
          >
            结束面试
          </button>
        </div>
      </div>

      {/* Messages */}
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
                <div className="flex gap-1.5">
                  <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                  <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                  <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
                </div>
              )}
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div className="border-t pt-4 flex gap-3">
        {voiceMode ? (
          // Voice mode — record button
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
          // Text mode — textarea + send
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
    </div>
  );
}
