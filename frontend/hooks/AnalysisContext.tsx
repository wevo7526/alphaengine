"use client";

import { createContext, useContext, type ReactNode } from "react";
import { useAnalysis, type AnalysisRun } from "./useAnalysis";

interface AnalysisContextType {
  runs: AnalysisRun[];
  activeRun: string | null;
  analyze: (query: string) => Promise<void>;
  removeRun: (id: string) => void;
}

const AnalysisContext = createContext<AnalysisContextType | null>(null);

export function AnalysisProvider({ children }: { children: ReactNode }) {
  const analysis = useAnalysis();
  return (
    <AnalysisContext.Provider value={analysis}>
      {children}
    </AnalysisContext.Provider>
  );
}

export function useAnalysisContext(): AnalysisContextType {
  const ctx = useContext(AnalysisContext);
  if (!ctx) throw new Error("useAnalysisContext must be used within AnalysisProvider");
  return ctx;
}
