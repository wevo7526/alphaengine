"use client";

import Link from "next/link";
import { TerminalHeader } from "@/components/TerminalHeader";
import { RiskGatesEditor } from "@/components/RiskGatesEditor";

/**
 * Risk gates configuration page.
 *
 * The editor itself lives in components/RiskGatesEditor — also embedded
 * inside the main Settings page. This page exists for direct linking
 * (e.g. from older memos or notifications) and keeps the same UX.
 */
export default function RiskConfigPage() {
  return (
    <div className="p-8 max-w-[1280px] mx-auto space-y-6">
      <TerminalHeader
        eyebrow="RISK GATES"
        title="Per-user overrides"
        sub={
          <>
            Every gate falls back to the platform default unless you override it
            here. Changes take effect on your next trade and drive both the
            pre-trade risk check and the optimizer. Need context?{" "}
            <Link href="/risk" className="text-accent hover:underline">
              View live risk dashboard →
            </Link>
          </>
        }
      />

      <RiskGatesEditor />
    </div>
  );
}
