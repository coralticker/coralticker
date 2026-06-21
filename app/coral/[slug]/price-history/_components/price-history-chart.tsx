// Single overlaid price-history plot (CTK-162 D-3, per-VENDOR rewrite). Server
// component, pure SVG — all geometry from lib/chart/price-history-geometry. One
// heavy near-black FLOOR line (cross-vendor daily-min) with a thin cream casing
// so it punches through, over one lighter LINE PER VENDOR. No fallback layout
// (/lead-frontend: single plot for v1; the retired small-multiples is gone).
//
// Draw order is load-bearing (D-3): vendor lines UNDER, then the floor's cream
// casing UNDER its own near-black line, then end-labels on top. Forest never
// appears. Single-day runs render as dots (no line to draw).
//
// Line weight (/brand-manager lock 2026-06-21): the floor is 2.75px near-black +
// cream casing (the hero); each vendor line is 1px PURE near-black (#1A1A1A via
// stroke-ink) — THICKNESS is the only differentiator, never a mute tone or
// opacity (the muted treatment was sub-AA, which is why it's out).
//
// N-annotation (per-vendor in-stock listing count, /brand-manager lock): the
// listingCount rides each end-label in near-black Plex Mono, de-emphasized by
// SMALLER SIZE only — no mute (sub-AA), no forest, no mid-dot. The legend gloss
// explains it.

import type { CoralEnvelopePoint } from '@/lib/queries/coral-price';
import {
  type Domain,
  type VendorTrack,
  FRAME,
  floorGeometry,
  vendorLineGeometry,
  endLabels,
  viewboxWidth,
  xTicks,
  yScale,
} from '@/lib/chart/price-history-geometry';
import { vendorShorthand } from '@/lib/format/vendor-label';

interface PriceHistoryChartProps {
  envelope: CoralEnvelopePoint[];
  tracks: VendorTrack[];
  domain: Domain;
  displayNameBySlug: Record<string, string>;
  ariaLabel: string;
}

export function PriceHistoryChart({
  envelope,
  tracks,
  domain,
  displayNameBySlug,
  ariaLabel,
}: PriceHistoryChartProps) {
  const labelFor = (slug: string) =>
    vendorShorthand(slug, displayNameBySlug[slug] ?? slug);
  const floor = floorGeometry(envelope, domain);
  const labels = endLabels(tracks, domain, labelFor);
  const xs = xTicks(domain);
  const vbW = viewboxWidth(labels);

  // N-annotation: current (last-day) in-stock listing count per vendor slug,
  // paired to its end-label below (/brand-manager-locked styling).
  const nBySlug: Record<string, number> = {};
  for (const t of tracks) {
    const last = t.points[t.points.length - 1];
    if (last) nBySlug[t.vendorSlug] = last.listingCount;
  }

  return (
    <div className="mt-4">
      <svg
        viewBox={`0 0 ${vbW} ${FRAME.vbH}`}
        role="img"
        aria-label={ariaLabel}
        className="block w-full h-auto overflow-visible"
      >
        {/* gridlines + axis baseline */}
        {domain.yTicks.map((p) => (
          <line
            key={`grid-${p}`}
            className="stroke-line"
            strokeWidth={1}
            x1={FRAME.plotLeft}
            y1={yScale(p, domain)}
            x2={FRAME.plotRight}
            y2={yScale(p, domain)}
          />
        ))}
        <line
          className="stroke-line"
          strokeWidth={1}
          x1={FRAME.plotLeft}
          y1={FRAME.axisY}
          x2={FRAME.plotRight}
          y2={FRAME.axisY}
        />

        {/* y-axis price labels */}
        {domain.yTicks.map((p) => (
          <text
            key={`ylab-${p}`}
            className="font-mono fill-ink"
            fontSize={10.5}
            textAnchor="end"
            x={FRAME.plotLeft - 8}
            y={yScale(p, domain) + 3.5}
          >
            ${p}
          </text>
        ))}

        {/* x-axis date labels */}
        {xs.map((tick, i) => (
          <text
            key={`xlab-${i}`}
            className="font-mono fill-ink"
            fontSize={10}
            textAnchor={i === xs.length - 1 ? 'end' : 'start'}
            x={tick.x}
            y={FRAME.xLabelY}
          >
            {tick.label}
          </text>
        ))}

        {/* per-vendor lines — drawn first, under the floor */}
        {tracks.map((track) => {
          const g = vendorLineGeometry(track, domain);
          return (
            <g key={`vendor-${track.vendorId}`}>
              {g.paths.map((d, i) => (
                <path
                  key={`p-${i}`}
                  className="stroke-ink"
                  fill="none"
                  strokeWidth={1}
                  strokeLinejoin="miter"
                  strokeLinecap="butt"
                  d={d}
                />
              ))}
              {g.dots.map((dot, i) => (
                <circle key={`d-${i}`} className="fill-ink" cx={dot.x} cy={dot.y} r={2} />
              ))}
            </g>
          );
        })}

        {/* floor: cream casing UNDER, near-black ON TOP, per contiguous run */}
        {floor.paths.map((d, i) => (
          <path
            key={`floor-casing-${i}`}
            className="stroke-cream"
            fill="none"
            strokeWidth={6}
            strokeLinejoin="miter"
            strokeLinecap="butt"
            d={d}
          />
        ))}
        {floor.paths.map((d, i) => (
          <path
            key={`floor-${i}`}
            className="stroke-ink"
            fill="none"
            strokeWidth={2.75}
            strokeLinejoin="miter"
            strokeLinecap="butt"
            d={d}
          />
        ))}
        {floor.dots.map((dot, i) => (
          <circle key={`floor-dot-${i}`} className="fill-ink" cx={dot.x} cy={dot.y} r={3.2} />
        ))}

        {/* end-labels last (on top). Muted "·N" = PROVISIONAL listing-count
            annotation, pending /brand-manager + /lead-frontend visual lock. */}
        {labels.map((label, i) => {
          const n = nBySlug[label.vendorSlug];
          return (
            <text key={`endlab-${i}`} x={label.x} y={label.y}>
              <tspan className="font-mono fill-ink" fontSize={10.5} fontWeight={500}>
                {label.text}
              </tspan>
              {n !== undefined ? (
                <tspan className="font-mono fill-ink" fontSize={9}>
                  {` ${n}`}
                </tspan>
              ) : null}
            </text>
          );
        })}
      </svg>
    </div>
  );
}
