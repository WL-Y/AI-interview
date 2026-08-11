"use client";

import { useRef, useState } from "react";
import { useInterviewStore } from "@/stores/interview";

export function LandingScreen() {
  const { createSession, startInterview, isLoading, resumeFile, setResumeFile } =
    useInterviewStore();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);

  const handleStart = async () => {
    setError(null);
    try {
      await createSession(resumeFile ?? undefined);
      await startInterview();
    } catch (e: any) {
      setError(e.message || "创建面试失败，请重试");
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
          上传简历，AI 将根据你的背景定制专属面试
        </p>
      </div>

      <div className="w-full max-w-md space-y-5">
        {/* Resume upload */}
        <div>
          {resumeFile ? (
            // File selected — show card
            <div className="space-y-4">
              <div className="flex items-center gap-3 p-4 border-2 border-green-300 bg-green-50 rounded-xl">
                <span className="text-2xl">📄</span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-green-800 truncate">
                    {resumeFile.name}
                  </p>
                  <p className="text-xs text-green-600">
                    {(resumeFile.size / 1024).toFixed(0)} KB · 已就绪
                  </p>
                </div>
                <button
                  onClick={handleRemoveFile}
                  className="text-xs text-green-600 hover:text-red-500 transition-colors px-2 py-1"
                >
                  移除
                </button>
              </div>

              {/* Error message */}
              {error && (
                <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                  {error}
                </div>
              )}

              {/* Start button */}
              <button
                onClick={handleStart}
                disabled={isLoading}
                className="w-full py-3 bg-brand-600 text-white rounded-xl font-medium text-lg
                           hover:bg-brand-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isLoading ? "正在分析简历、生成面试..." : "开始面试"}
              </button>
            </div>
          ) : (
            // Upload prompt
            <label className="flex flex-col items-center gap-3 p-10 border-2 border-dashed border-gray-200
                              rounded-2xl cursor-pointer hover:border-brand-400 hover:bg-brand-50/50 transition-colors">
              <span className="text-4xl">📄</span>
              <span className="text-base font-medium text-gray-700">
                上传简历，开始模拟面试
              </span>
              <span className="text-sm text-gray-400">
                支持 PDF / DOCX / TXT 格式
              </span>
              <span className="text-xs text-brand-500 mt-1">
                AI 将根据你的技术栈和项目经验，量身定制面试题目
              </span>
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
      </div>
    </div>
  );
}
