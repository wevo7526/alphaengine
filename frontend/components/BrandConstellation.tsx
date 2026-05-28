/**
 * BrandConstellation — slow, perpetual network animation for the auth panel.
 *
 * Conveys "agents connected by data" with concentric rotating rings,
 * orbital nodes, pulsing core, drifting accent particles, and a slow
 * radar sweep. All motion is 30-180s so it reads as ambient and never
 * distracts from the auth controls.
 *
 * Pure SVG + CSS keyframes (declared in app/globals.css). No JS runtime,
 * no canvas, GPU-accelerated transforms only.
 */
export function BrandConstellation() {
  // Place orbital nodes at evenly-spaced points around the center.
  // We hand-place them so the rotation centroid is exact and the lines
  // connect cleanly from each node back to the core hub.
  const ORBIT_OUTER = 220;
  const ORBIT_INNER = 130;
  const center = 320;
  const outerCount = 8;
  const innerCount = 5;

  // Round to 2 decimals so SSR and client produce identical SVG strings.
  // Math.cos / Math.sin can differ by 1 ULP between Node and browser JS
  // engines, which triggers React's hydration mismatch warning even
  // though the rendered output is visually identical.
  const round2 = (n: number) => Math.round(n * 100) / 100;
  const outerNodes = Array.from({ length: outerCount }, (_, i) => {
    const angle = (i / outerCount) * 2 * Math.PI - Math.PI / 2;
    return {
      cx: round2(center + ORBIT_OUTER * Math.cos(angle)),
      cy: round2(center + ORBIT_OUTER * Math.sin(angle)),
      key: i,
    };
  });
  const innerNodes = Array.from({ length: innerCount }, (_, i) => {
    const angle = (i / innerCount) * 2 * Math.PI - Math.PI / 2;
    return {
      cx: round2(center + ORBIT_INNER * Math.cos(angle)),
      cy: round2(center + ORBIT_INNER * Math.sin(angle)),
      key: i,
    };
  });

  return (
    <div
      className="absolute inset-0 flex items-center justify-center overflow-hidden pointer-events-none"
      aria-hidden="true"
    >
      <svg
        viewBox="0 0 640 640"
        className="w-[140%] h-[140%] max-w-none opacity-90"
      >
        <defs>
          {/* Radial fade for the core */}
          <radialGradient id="coreGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.9" />
            <stop offset="50%" stopColor="#3b82f6" stopOpacity="0.2" />
            <stop offset="100%" stopColor="#3b82f6" stopOpacity="0" />
          </radialGradient>
          {/* Soft accent halo behind the entire constellation */}
          <radialGradient id="ambientHalo" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.12" />
            <stop offset="60%" stopColor="#3b82f6" stopOpacity="0.03" />
            <stop offset="100%" stopColor="#3b82f6" stopOpacity="0" />
          </radialGradient>
          {/* Scan-sweep gradient (a soft wedge of light that rotates) */}
          <linearGradient id="sweepGradient" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#3b82f6" stopOpacity="0" />
            <stop offset="40%" stopColor="#3b82f6" stopOpacity="0" />
            <stop offset="100%" stopColor="#3b82f6" stopOpacity="0.18" />
          </linearGradient>
        </defs>

        {/* Ambient backdrop glow */}
        <circle cx={center} cy={center} r="300" fill="url(#ambientHalo)" />

        {/* Outermost halo ring (very slow rotation, dashed) */}
        <g className="constellation-halo">
          <circle
            cx={center}
            cy={center}
            r="290"
            fill="none"
            stroke="rgba(250,250,250,0.04)"
            strokeWidth="1"
            strokeDasharray="2 6"
          />
          <circle
            cx={center}
            cy={center}
            r="260"
            fill="none"
            stroke="rgba(59,130,246,0.08)"
            strokeWidth="1"
          />
        </g>

        {/* Scan sweep — a faint wedge of light rotating slowly.
            Coordinates pre-rounded so SSR matches client (avoids React
            hydration warning from floating-point precision drift). */}
        <g className="constellation-scan">
          <path
            d={`M ${center} ${center} L ${center + 280} ${center} A 280 280 0 0 1 ${round2(
              center + 280 * Math.cos((40 * Math.PI) / 180)
            )} ${round2(center + 280 * Math.sin((40 * Math.PI) / 180))} Z`}
            fill="url(#sweepGradient)"
          />
        </g>

        {/* Outer orbital ring — counter-rotating */}
        <g className="constellation-orbit-2">
          {/* Connection lines between adjacent outer nodes (forms an octagon) */}
          {outerNodes.map((n, i) => {
            const next = outerNodes[(i + 1) % outerCount];
            return (
              <line
                key={`outer-edge-${i}`}
                x1={n.cx}
                y1={n.cy}
                x2={next.cx}
                y2={next.cy}
                stroke="rgba(59,130,246,0.18)"
                strokeWidth="1"
                className="constellation-line"
                style={{ animationDelay: `${i * 0.6}s` }}
              />
            );
          })}
          {/* Outer nodes */}
          {outerNodes.map((n, i) => (
            <g key={`outer-node-${i}`} className="constellation-node" style={{ animationDelay: `${i * 0.5}s` }}>
              <circle cx={n.cx} cy={n.cy} r="14" fill="rgba(59,130,246,0.12)" />
              <circle cx={n.cx} cy={n.cy} r="5" fill="#3b82f6" />
              <circle cx={n.cx} cy={n.cy} r="2" fill="#fafafa" />
            </g>
          ))}
        </g>

        {/* Inner ring — clockwise, spokes to center */}
        <g className="constellation-orbit-1">
          {/* Spokes from each inner node to center */}
          {innerNodes.map((n, i) => (
            <line
              key={`inner-spoke-${i}`}
              x1={center}
              y1={center}
              x2={n.cx}
              y2={n.cy}
              stroke="rgba(59,130,246,0.28)"
              strokeWidth="1"
              className="constellation-line"
              style={{ animationDelay: `${i * 0.8}s` }}
            />
          ))}
          {innerNodes.map((n, i) => (
            <g key={`inner-node-${i}`} className="constellation-node" style={{ animationDelay: `${i * 0.4}s` }}>
              <circle cx={n.cx} cy={n.cy} r="11" fill="rgba(59,130,246,0.18)" />
              <circle cx={n.cx} cy={n.cy} r="4.5" fill="#3b82f6" />
            </g>
          ))}
        </g>

        {/* Central hub — glowing core */}
        <g>
          <circle cx={center} cy={center} r="64" fill="url(#coreGlow)" />
          <g className="constellation-core">
            <circle cx={center} cy={center} r="22" fill="rgba(59,130,246,0.22)" />
            <circle cx={center} cy={center} r="11" fill="#3b82f6" />
            <circle cx={center} cy={center} r="4" fill="#fafafa" />
          </g>
        </g>

        {/* Drifting accent particles (signal green for contrast) */}
        <g className="constellation-drift-1">
          <circle cx={center - 180} cy={center + 60} r="2.5" fill="#10b981" opacity="0.9" />
          <circle cx={center - 220} cy={center - 90} r="1.5" fill="#10b981" opacity="0.6" />
        </g>
        <g className="constellation-drift-2">
          <circle cx={center + 180} cy={center - 40} r="2.5" fill="#10b981" opacity="0.9" />
          <circle cx={center + 230} cy={center + 110} r="1.5" fill="#10b981" opacity="0.6" />
          <circle cx={center + 90} cy={center + 220} r="2" fill="#10b981" opacity="0.7" />
        </g>
      </svg>
    </div>
  );
}
