"use client";

import { useInterviewStore } from "@/stores/interview";
import { LandingScreen } from "@/components/LandingScreen";
import { InterviewScreen } from "@/components/InterviewScreen";
import { ReportScreen } from "@/components/ReportScreen";

export default function Home() {
  const screen = useInterviewStore((s) => s.screen);

  switch (screen) {
    case "landing":
      return <LandingScreen />;
    case "interview":
      return <InterviewScreen />;
    case "report":
      return <ReportScreen />;
    default:
      return <LandingScreen />;
  }
}
