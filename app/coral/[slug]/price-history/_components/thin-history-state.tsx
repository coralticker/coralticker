// Thin-history state (CTK-162 D-3): one recorded observation, no line to draw.
//
// Tier-1A trust rule (captured /code-review): NEVER render a fabricated $0. The
// per-vendor source emits only real in-stock mins, so when an observation comes
// from there `price` is a real number → dot state. When there is no per-vendor
// priced data and the page falls back to availability, `price` can be null
// (price-on-request / auction) → render "price on request" (the auction
// null-price convention), with NO dot and NO $-axis. There is no path that
// shows a $0 point/tick.
//
// COPY IS PROVISIONAL — voice-approved DIRECTION from the round-2 mock, pending
// /copy-writer final wording + Jon's eyeball before it locks.

import { niceTicksWithin, type Frame } from '@/lib/chart/price-history-geometry';

// Compact frame for the dot state — shorter than the full chart (no series to
// give height meaning).
const THIN_FRAME: Frame = {
  vbW: 760,
  vbH: 200,
  plotLeft: 64,
  plotRight: 720,
  plotTop: 24,
  plotBottom: 150,
  axisY: 160,
  xLabelY: 178,
};

interface ThinObservation {
  dateLabel: string; // pre-formatted "MMM D" (page owns the date math)
  price: number | null; // null = price on request (NEVER rendered as $0)
}

const GAP_NOTE =
  // PROVISIONAL gap-moment copy — pending /copy-writer + Jon.
  "Not much history with me yet — I started tracking this one recently. I’ll fill the line in as the price moves.";

export function ThinHistoryState({ observation }: { observation: ThinObservation }) {
  // Null-price (price-on-request / auction): no honest y-position, so no dot and
  // no $-axis — a single mono line carries the state instead of a fake $0 point.
  if (observation.price === null) {
    return (
      <div>
        {observation.dateLabel ? (
          <p className="font-mono text-sm uppercase tracking-[0.06em] text-ink mt-6">
            Price on request &middot; {observation.dateLabel}
          </p>
        ) : null}
        <p className="text-base text-ink mt-4">{GAP_NOTE}</p>
      </div>
    );
  }

  const price = observation.price;
  const ticks = niceTicksWithin(price * 0.95, price * 1.05, 2);
  const yMin = price * 0.95;
  const yMax = price * 1.05;
  const plotH = THIN_FRAME.plotBottom - THIN_FRAME.plotTop;
  const yOf = (p: number) => THIN_FRAME.plotTop + ((yMax - p) / (yMax - yMin)) * plotH;
  const dotX = THIN_FRAME.plotRight - 30; // sits near (not on) the right edge
  const dotY = yOf(price);

  return (
    <div>
      <div className="mt-4">
        <svg
          viewBox={`0 0 ${THIN_FRAME.vbW} ${THIN_FRAME.vbH}`}
          role="img"
          aria-label={`One recorded price point: $${price}, ${observation.dateLabel}.`}
          className="block w-full h-auto overflow-visible"
        >
          {ticks.map((p) => (
            <line
              key={`g-${p}`}
              className="stroke-line"
              strokeWidth={1}
              x1={THIN_FRAME.plotLeft}
              y1={yOf(p)}
              x2={THIN_FRAME.plotRight}
              y2={yOf(p)}
            />
          ))}
          <line
            className="stroke-line"
            strokeWidth={1}
            x1={THIN_FRAME.plotLeft}
            y1={THIN_FRAME.axisY}
            x2={THIN_FRAME.plotRight}
            y2={THIN_FRAME.axisY}
          />
          {ticks.map((p) => (
            <text
              key={`yl-${p}`}
              className="font-mono fill-ink"
              fontSize={10.5}
              textAnchor="end"
              x={THIN_FRAME.plotLeft - 8}
              y={yOf(p) + 3.5}
            >
              ${p}
            </text>
          ))}
          <circle className="fill-ink" cx={dotX} cy={dotY} r={3.2} />
          <text
            className="font-mono fill-ink"
            fontSize={10}
            textAnchor="end"
            x={THIN_FRAME.plotRight}
            y={THIN_FRAME.xLabelY}
          >
            {observation.dateLabel}
          </text>
        </svg>
      </div>

      <p className="text-base text-ink mt-4">{GAP_NOTE}</p>
    </div>
  );
}
