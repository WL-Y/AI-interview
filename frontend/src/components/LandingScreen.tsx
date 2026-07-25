"use client";

import { useState, useRef } from "react";
import { useInterviewStore } from "@/stores/interview";

const POSITIONS = [
  "前端工程师",
  "后端工程师",
  "算法工程师",
  "数据分析师",
  "产品经理",
  "DevOps/SRE",
];

export function LandingScreen() {
  const [position, setPosition] = useState("前端工程师");
  const { createSession, startInterview, isLoading, resumeFile, setResumeFile } =
    useInterviewStore();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleStart = async () => {
    try {
      await createSession(position, resumeFile ?? undefined);
      await startInterview();
    } catch {
      // Error handling is in the store
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] ?? null;
    setResumeFile(file);
  };

  const handleRemoveFile = () => {
    setResumeFile(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  return (
    <div className="interview-container items-center justify-center gap-8">
      <div className="text-center space-y-2">
        <h1 className="text-4xl font-bold tracking-tight">AI 模拟面试</h1>
        <p className="text-gray-500 text-lg">
          语音优先 · 半结构化 · 智能评分
        </p>
      </div>

      <div className="w-full max-w-md space-y-5">
        {/* Position selector */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            目标岗位
          </label>
          <div className="grid grid-cols-3 gap-2">
            {POSITIONS.map((p) => (
              <button
                key={p}
                onClick={() => setPosition(p)}
                className={`px-3 py-2 text-sm rounded-lg border transition-colors
                  ${position === p
                    ? "border-brand-500 bg-brand-50 text-brand-700 font-medium"
                    : "border-gray-200 hover:border-gray-300 text-gray-600"
                  }`}
              >
                {p}
              </button>
            ))}
          </div>
        </div>

        {/* Resume upload */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            上传简历（可选，让出题更精准）
          </label>

          {resumeFile ? (
            // File selected
            <div className="flex items-center gap-3 p-3 border border-green-200 bg-green-50 rounded-lg">
              <span className="text-sm text-green-700 truncate flex-1">
                {resumeFile.name}
              </span>
              <button
                onClick={handleRemoveFile}
                className="text-xs text-green-600 hover:text-red-500 transition-colors"
              >
                移除
              </button>
            </div>
          ) : (
            // Upload button
            <label className="flex flex-col items-center gap-2 p-6 border-2 border-dashed border-gray-200
                              rounded-xl cursor-pointer hover:border-brand-400 hover:bg-brand-50/50 transition-colors">
              <span className="text-2xl">📄</span>
              <span className="text-sm text-gray-500">点击上传 PDF / DOCX / TXT</span>
              <span className="text-xs text-gray-400">支持简历文件，AI 将根据简历个性化出题</span>
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.docx,.doc,.txt"
                onChange={handleFileChange}
                className="hidden"
              />
            </label>
          )}
        </div>

        {/* Start button */}
        <button
          onClick={handleStart}
          disabled={isLoading}
          className="w-full py-3 bg-brand-600 text-white rounded-xl font-medium
                     hover:bg-brand-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isLoading ? "正在分析简历、准备面试..." : "开始面试"}
        </button>
      </div>
    </div>
  );
}
