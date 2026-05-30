"use client";

import Link from "next/link";
import { useUser } from "@clerk/nextjs";

/**
 * Portal — the paid infrastructure surface (BYO data, keys, provided-mode).
 * Gated (SessionGuard requires sign-in). Distinct from the demo desk: the
 * framing is "your data, your keys, nothing stored". Key provisioning + live
 * usage land with T12 (Clerk org -> key) + the gateway deploy; until then this
 * shows the connection contract and the trial state.
 */
export default function PortalPage() {
  const { user } = useUser();
  const first = user?.firstName || user?.fullName?.split(" ")[0];
  return (
    <div className="min-h-screen bg-bg-primary text-text-primary">
      <header className="border-b border-border-primary/60 bg-bg-primary/85 backdrop-blur-lg sticky top-0 z-40">
        <div className="max-w-[1100px] mx-auto px-6 h-14 flex items-center justify-between">
          <Link href="/" className="text-[15px] font-semibold tracking-tight">
            alpha<span className="text-brand">engine</span>
            <span className="ml-2 text-[11px] font-mono tracking-[0.18em] text-text-quaternary">/ PORTAL</span>
          </Link>
          <div className="flex items-center gap-3 text-[12px]">
            <Link href="/docs" className="text-text-tertiary hover:text-text-primary transition-colors">DOCS</Link>
            <Link href="/dashboard" className="text-text-tertiary hover:text-text-primary transition-colors">DEMO DESK</Link>
          </div>
        </div>
      </header>

      <div className="max-w-[1100px] mx-auto px-6 py-14">
        <div className="rounded-sm border border-border-primary bg-bg-surface/40 px-5 py-3 mb-10 flex items-center gap-3">
          <span className="text-[10px] font-mono tracking-[0.16em] text-text-primary">YOUR DATA · YOUR KEYS · NOTHING STORED</span>
          <span className="text-[11px] text-text-quaternary">Authenticated requests run in provided-mode. The fetch layer is unreachable.</span>
        </div>

        <p className="text-[10px] font-mono tracking-[0.22em] text-text-quaternary mb-4">
          <span className="text-text-tertiary">///</span> CONNECT
        </p>
        <h1 className="font-display text-[32px] sm:text-[40px] font-semibold tracking-[-0.01em] leading-[1.08] mb-4">
          Welcome{first ? `, ${first}` : ""}. Wire it into your stack.
        </h1>
        <p className="text-[15px] text-text-secondary leading-relaxed mb-10 max-w-xl">
          Point your agent at the MCP endpoint or your bot at the REST API with the
          key below. Both speak the same versioned SignalEnvelope.
        </p>

        <div className="grid lg:grid-cols-2 gap-6">
          <Panel title="YOUR API KEY" note="beta">
            <div className="font-mono text-[12px] text-text-secondary bg-bg-primary/60 border border-border-primary/60 rounded-sm px-3 py-2.5 flex items-center justify-between">
              <span>ae_live_••••••••••••••••</span>
              <span className="text-[10px] tracking-[0.16em] text-text-quaternary">PROVISIONING</span>
            </div>
            <p className="mt-3 text-[12px] text-text-tertiary leading-relaxed">
              Live key provisioning lands with the gateway deploy. Your trial key
              will appear here and works across REST and MCP.
            </p>
          </Panel>

          <Panel title="USAGE" note="stateless">
            <div className="grid grid-cols-3 gap-px bg-border-primary/40 border border-border-primary/40 rounded-sm overflow-hidden text-center">
              {[["CALLS", "0"], ["JOBS", "0"], ["P50 ms", "--"]].map(([k, v]) => (
                <div key={k} className="bg-bg-surface px-2 py-3">
                  <p className="text-[8px] font-mono tracking-[0.18em] text-text-quaternary mb-1">{k}</p>
                  <p className="text-[15px] font-mono text-text-primary">{v}</p>
                </div>
              ))}
            </div>
            <p className="mt-3 text-[12px] text-text-tertiary leading-relaxed">Counts only. We never log your payload values.</p>
          </Panel>

          <Panel title="MCP · for your agent">
            <Pre>{`{
  "mcpServers": {
    "alphaengine": {
      "url": "https://mcp.alphaengine.dev",
      "headers": { "Authorization": "Bearer $ALPHAENGINE_KEY" }
    }
  }
}`}</Pre>
          </Panel>

          <Panel title="REST · for your bot">
            <Pre>{`curl https://api.alphaengine.dev/v1/tools/compute_var_cvar \\
  -H "Authorization: Bearer $ALPHAENGINE_KEY" \\
  -d '{ "portfolio_returns": [ ... ] }'`}</Pre>
          </Panel>
        </div>

        <div className="mt-10 flex items-center gap-4 flex-wrap">
          <Link href="/docs" className="px-5 py-2.5 rounded-sm bg-white text-bg-primary text-[13px] font-semibold hover:bg-zinc-200 transition-colors">Read the quickstart</Link>
          <span className="text-[12px] text-text-quaternary">SDK: <span className="font-mono text-text-tertiary">pip install alphaengine</span> (coming with the deploy)</span>
        </div>
      </div>
    </div>
  );
}

function Panel({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <div className="rounded-sm border border-border-primary bg-bg-surface overflow-hidden">
      <div className="px-4 py-2 border-b border-border-primary/60 flex items-center justify-between text-[9px] font-mono uppercase tracking-wider text-text-quaternary">
        <span>{title}</span>{note && <span className="text-text-tertiary">{note}</span>}
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}
function Pre({ children }: { children: React.ReactNode }) {
  return <pre className="text-[11px] leading-[1.6] font-mono text-text-tertiary overflow-x-auto whitespace-pre">{children}</pre>;
}
