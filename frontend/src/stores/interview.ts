"use client";

import { create } from "zustand";

// ── Types (mirrored from backend models) ──────────────────

export type Phase =
  | "introduction"
  | "project_deep_dive"
  | "tech_foundation"
  | "q_and_a";

export type InterviewStatus = "prep" | "live" | "post" | "aborted";

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

export interface InterviewContext {
  session_id: string;
  status: InterviewStatus;
  candidate_profile: string;
  jd_summary: string;
  current_phase: Phase;
  transcript: Turn[];
  scorecard: ScoreCard | null;
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

  // Actions
  createSession: (position: string, resume?: File) => Promise<void>;
  startInterview: () => Promise<void>;
  sendMessage: (content: string) => Promise<void>;
  sendVoice: (sessionId: string, text: string) => Promise<{ text: string; audioBase64: string }>;
  finishInterview: () => Promise<void>;
}

const API_BASE = "/api/interview";

// ── API helper ───────────────────────────────────────────

async function apiCall<T>(
  url: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(url, options);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as any).message || `请求失败 (${res.status})`);
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

  // ── API calls ──────────────────────────────────────────

  createSession: async (position, resume) => {
    set({ isLoading: true });
    try {
      const formData = new FormData();
      formData.append("position", position);
      if (resume) formData.append("resume", resume);
      const session = await apiCall<any>(`${API_BASE}/create`, {
        method: "POST",
        body: formData,
      });
      set({ session, isLoading: false });
    } catch (e: any) {
      set({ isLoading: false });
      throw e;
    }
  },

  startInterview: async () => {
    const { session } = get();
    if (!session) return;
    set({ isLoading: true });
    try {
      const updated = await apiCall<any>(`${API_BASE}/${session.session_id}/start`, { method: "POST" });
      set({ session: updated, screen: "interview", isLoading: false });
    } catch (e: any) {
      set({ isLoading: false });
      throw e;
    }
  },

  sendMessage: async (content) => {
    const { session } = get();
    if (!session) return;
    set({ isLoading: true });
    try {
      const updated = await apiCall<any>(
        `${API_BASE}/${session.session_id}/send?content=${encodeURIComponent(content)}`,
        { method: "POST" },
      );
      set({ session: updated, textInput: "", isLoading: false });
    } catch (e: any) {
      set({ isLoading: false });
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

      // Update transcript
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
