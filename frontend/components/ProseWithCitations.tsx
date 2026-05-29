"use client";

import type { Citation } from "@/lib/types";

/**
 * ProseWithCitations — render memo prose with inline `[N]` footnote
 * anchors styled as small accent superscripts. Hover shows the source
 * label; click jumps to the citation in the CitationIndexPanel below.
 *
 * The backend's resolver guarantees every `[N]` token in `text` maps to
 * an entry in `index`; unresolved markers were stripped before persist.
 * If `index` is missing or the marker can't be matched (legacy memos),
 * we still render the bracket as plain accent text rather than breaking.
 */

const ANCHOR_RE = /\[(\d+)\]/g;

export function ProseWithCitations({
  text,
  index,
  className = "",
}: {
  text: string;
  index?: Citation[];
  className?: string;
}) {
  if (!text) return null;
  const byN = new Map<number, Citation>();
  for (const c of index ?? []) {
    if (c.n) byN.set(c.n, c);
  }

  // Split prose into paragraphs first so we render line breaks consistently
  // with the legacy whitespace-pre-wrap version. Within each paragraph,
  // walk the text and emit alternating spans + anchor links.
  const paragraphs = text.split(/\n{2,}/);

  return (
    <div className={["space-y-4", className].join(" ")}>
      {paragraphs.map((para, pi) => {
        const trimmed = para.replace(/^\s+/, "");
        if (!trimmed) return null;
        return (
          <p
            key={pi}
            className="text-[13px] text-text-secondary leading-relaxed whitespace-pre-wrap"
          >
            {renderWithAnchors(trimmed, byN)}
          </p>
        );
      })}
    </div>
  );
}

function renderWithAnchors(
  text: string,
  byN: Map<number, Citation>
): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let last = 0;
  let matchIdx = 0;
  ANCHOR_RE.lastIndex = 0;
  for (const m of text.matchAll(ANCHOR_RE)) {
    const start = m.index ?? 0;
    if (start > last) {
      out.push(text.slice(last, start));
    }
    const n = Number(m[1]);
    const cite = byN.get(n);
    out.push(<CitationAnchor key={`a-${matchIdx++}`} n={n} citation={cite} />);
    last = start + m[0].length;
  }
  if (last < text.length) {
    out.push(text.slice(last));
  }
  return out;
}

function CitationAnchor({ n, citation }: { n: number; citation?: Citation }) {
  const title = citation?.label ?? `Citation ${n}`;
  const cls =
    "inline-flex items-center justify-center align-super px-1 py-px ml-0.5 rounded " +
    "text-[9px] font-mono font-semibold tabular-nums leading-none " +
    "text-accent hover:bg-accent/[0.08] transition-colors";

  // External URL: open the source directly. No URL: jump to in-page index.
  if (citation?.url) {
    return (
      <a
        href={citation.url}
        target="_blank"
        rel="noopener noreferrer"
        title={title}
        className={cls}
      >
        [{n}]
      </a>
    );
  }
  return (
    <a href={`#cite-${n}`} title={title} className={cls}>
      [{n}]
    </a>
  );
}
