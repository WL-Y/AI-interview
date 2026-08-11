"use client";

import { create } from "zustand";

// ── Types (mirrored from backend models) ──────────────────

export type Phase =
  | "introduction"
  | "project_deep_dive"
  | "tech_foundation"
  | "q_and_a";

export type InterviewStatus = "prep" | "live" | "paused" | "post" | "aborted";

export type CompetencyDimension =
  | "tech_depth"
  | "project_experience"
  | "communication"
  | "role_fit";

export interface Turn {
  role: "interviewer" | "candidate" | "system";
  content: string;
  phase: Phase;
  timestamp: string;
}

export interface DimensionScore {
  dimension: CompetencyDimension;
  score: number;
  comment: string;
}

export interface ScoreCard {
  overall_score: number;
  dimension_scores: DimensionScore[];
  strengths: string[];
  weaknesses: string[];
  improvement_plan: string;
}

export interface SkillEstimate {
  score: number;
  confidence: number;
  evidence_count: number;
  importance?: number;
  coverage?: number;
}

export interface ProgressData {
  current_phase: string;
  current_question_index: number;
  total_questions: number;
  answered_questions: number;
  elapsed_seconds: number;
  status: string;
  phase_order: string[];
  current_phase_label: string;
  coverage_pct: number;
  adaptive_mode: boolean;
  skills: Record<string, SkillEstimate>;
  current_topic: string;
  latest_draft_score: number | null;
  latest_feedback: string;
}

export interface AnswerRecord {
  question_id: string;
  question_text: string;
  answer_summary: string;
  dimension: CompetencyDimension;
  draft_score: number | null;
  notes: string;
  candidate_answer: string;
}

export interface InterviewContext {
  session_id: string;
  status: InterviewStatus;
  candidate_profile: string;
  jd_summary: string;
  current_phase: Phase;
  transcript: Turn[];
  scorecard: ScoreCard | null;
  // Progress fields (new)
  total_questions: number;
  answered_questions: number;
  elapsed_seconds: number;
  answer_records: AnswerRecord[];
}

// ── UI-only state ─────────────────────────────────────────

export type Screen = "landing" | "interview" | "report";

interface InterviewStore {
  // Session
  session: InterviewContext | null;
  setSession: (session: InterviewContext) => void;

  // UI
  screen: Screen;
  setScreen: (screen: Screen) => void;
  isLoading: boolean;
  setIsLoading: (v: boolean) => void;

  // Text input (for mock mode)
  textInput: string;
  setTextInput: (v: string) => void;

  // Voice mode
  voiceMode: boolean;
  toggleVoiceMode: () => void;
  isRecording: boolean;
  setIsRecording: (v: boolean) => void;
  lastAudioBase64: string | null;
  setLastAudioBase64: (v: string | null) => void;

  // Resume
  resumeFile: File | null;
  setResumeFile: (f: File | null) => void;

  // Progress (polled)
  progress: ProgressData | null;

  // Last per-question feedback (shown in UI after each answer)
  lastDraftScore: number | null;
  lastFeedback: string;
  showFeedback: boolean;

  // Actions
  createSession: (resume?: File) => Promise<void>;
  startInterview: () => Promise<void>;
  sendMessage: (content: string) => Promise<void>;
  sendVoice: (sessionId: string, text: string) => Promise<{ text: string; audioBase64: string }>;
  pauseInterview: () => Promise<void>;
  resumeInterview: () => Promise<void>;
  fetchProgress: () => Promise<void>;
  dismissFeedback: () => void;
  finishInterview: () => Promise<void>;
}

// Direct backend during dev; through Next.js proxy in production
const API_BASE = typeof window !== "undefined" && window.location.hostname === "localhost"
  ? "http://localhost:8000/api/interview"
  : "/api/interview";

// ── API helper ───────────────────────────────────────────

async function apiCall<T>(
  url: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(url, options);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as any).detail || (body as any).message || `请求失败 (${res.status})`);
  }
  return res.json();
}

export const useInterviewStore = create<InterviewStore>((set, get) => ({
  session: null,
  setSession: (session) => set({ session }),

  screen: "landing",
  setScreen: (screen) => set({ screen }),

  isLoading: false,
  setIsLoading: (isLoading) => set({ isLoading }),

  textInput: "",
  setTextInput: (textInput) => set({ textInput }),

  // Voice mode
  voiceMode: false,
  toggleVoiceMode: () => set((s) => ({ voiceMode: !s.voiceMode })),
  isRecording: false,
  setIsRecording: (isRecording) => set({ isRecording }),
  lastAudioBase64: null,
  setLastAudioBase64: (lastAudioBase64) => set({ lastAudioBase64 }),

  // Resume
  resumeFile: null,
  setResumeFile: (resumeFile) => set({ resumeFile }),

  // Progress
  progress: null,

  // Per-question feedback
  lastDraftScore: null,
  lastFeedback: "",
  showFeedback: false,

  // ── API calls ──────────────────────────────────────────

  createSession: async (resume) => {
    set({ isLoading: true });
    try {
      const formData = new FormData();
      if (resume) formData.append("resume", resume);
      console.log("[createSession] Sending request with resume:", resume?.name, resume?.size);
      const session = await apiCall<any>(`${API_BASE}/create`, {
        method: "POST",
        body: formData,
      });
      console.log("[createSession] Got session:", session.session_id, "questions:", session.total_questions);
      set({ session, isLoading: false });
    } catch (e: any) {
      console.error("[createSession] Failed:", e.message);
      set({ isLoading: false });
      throw e;
    }
  },

  startInterview: async () => {
    const { session } = get();
    if (!session) {
      console.error("[startInterview] No session found!");
      return;
    }
    console.log("[startInterview] Starting interview for session:", session.session_id);
    set({ isLoading: true });
    try {
      const updated = await apiCall<any>(`${API_BASE}/${session.session_id}/start`, { method: "POST" });
      console.log("[startInterview] Interview started, switching to interview screen");
      set({ session: updated, screen: "interview", isLoading: false });
    } catch (e: any) {
      console.error("[startInterview] Failed:", e.message);
      set({ isLoading: false });
      throw e;
    }
  },

  sendMessage: async (content) => {
    const { session } = get();
    if (!session) return;

    // ── Optimistic: show candidate message immediately ──
    const optimisticTurn = {
      role: "candidate" as const,
      content,
      phase: session.current_phase,
      timestamp: new Date().toISOString(),
    };
    set({
      session: { ...session, transcript: [...session.transcript, optimisticTurn] },
      textInput: "",
      isLoading: true, // loading = waiting for AI response
    });

    try {
      const updated = await apiCall<any>(
        `${API_BASE}/${session.session_id}/send?content=${encodeURIComponent(content)}`,
        { method: "POST" },
      );
      const records: AnswerRecord[] = updated.answer_records || [];
      const lastRecord = records[records.length - 1];
      set({
        session: updated,
        isLoading: false,
        lastDraftScore: lastRecord?.draft_score ?? null,
        lastFeedback: lastRecord?.notes || "",
        showFeedback: true,
      });
    } catch (e: any) {
      console.error("[sendMessage] Failed:", e.message);
      // Roll back the optimistic update
      set({
        session: get().session ? { ...get().session!, transcript: session.transcript } : null,
        isLoading: false,
        textInput: content, // restore text so user can retry
      });
      throw e;
    }
  },

  sendVoice: async (sessionId, text) => {
    set({ isLoading: true });
    try {
      const data = await apiCall<any>(
        `${API_BASE}/${sessionId}/voice/send?text=${encodeURIComponent(text)}`,
        { method: "POST" },
      );
      const { session } = get();
      if (session) {
        set({
          session: {
            ...session,
            current_phase: data.phase,
            transcript: [
              ...session.transcript,
              { role: "candidate" as const, content: text, phase: data.phase, timestamp: new Date().toISOString() },
              { role: "interviewer" as const, content: data.text, phase: data.phase, timestamp: new Date().toISOString() },
            ],
          },
          lastAudioBase64: data.audio_base64 || null,
          isLoading: false,
        });
      } else {
        set({ isLoading: false });
      }
      return { text: data.text, audioBase64: data.audio_base64 || "" };
    } catch (e: any) {
      set({ isLoading: false });
      throw e;
    }
  },

  pauseInterview: async () => {
    const { session } = get();
    if (!session) return;
    try {
      const data = await apiCall<any>(
        `${API_BASE}/${session.session_id}/pause`,
        { method: "POST" },
      );
      set({
        session: { ...session, status: "paused", elapsed_seconds: data.elapsed_seconds },
      });
    } catch (e: any) {
      throw e;
    }
  },

  resumeInterview: async () => {
    const { session } = get();
    if (!session) return;
    set({ isLoading: true });
    try {
      const updated = await apiCall<any>(
        `${API_BASE}/${session.session_id}/resume`,
        { method: "POST" },
      );
      set({ session: updated, isLoading: false });
    } catch (e: any) {
      set({ isLoading: false });
      throw e;
    }
  },

  fetchProgress: async () => {
    const { session } = get();
    if (!session) return;
    try {
      const progress = await apiCall<ProgressData>(
        `${API_BASE}/${session.session_id}/progress`,
      );
      set({ progress });
    } catch {
      // Silently fail — progress is non-critical
    }
  },

  dismissFeedback: () => set({ showFeedback: false }),

  finishInterview: async () => {
    const { session } = get();
    if (!session) return;
    set({ isLoading: true });
    try {
      const updated = await apiCall<any>(
        `${API_BASE}/${session.session_id}/finish`,
        { method: "POST" },
      );
      set({ session: updated, screen: "report", isLoading: false });
    } catch (e: any) {
      set({ isLoading: false });
      throw e;
    }
  },
}));
