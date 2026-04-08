"use client";

import type { ReactNode } from "react";
import { AnalysisProvider } from "@/hooks/AnalysisContext";

export function Providers({ children }: { children: ReactNode }) {
  return <AnalysisProvider>{children}</AnalysisProvider>;
}
