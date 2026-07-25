"use client";

import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;

      return (
        <div className="interview-container items-center justify-center gap-4 text-center">
          <div className="text-4xl">😵</div>
          <h2 className="text-xl font-semibold text-gray-800">出了点问题</h2>
          <p className="text-sm text-gray-500 max-w-sm">
            {this.state.error?.message || "发生了未知错误"}
          </p>
          <button
            onClick={() => {
              this.setState({ hasError: false, error: null });
              window.location.reload();
            }}
            className="px-6 py-2 bg-brand-600 text-white rounded-xl text-sm
                       hover:bg-brand-700 transition-colors"
          >
            刷新重试
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
