import { useState } from "react";
import { clock } from "../lib/format";

const ORDER = ["INFO", "WARNING", "ERROR", "CRITICAL"]; // stacked bottom -> top
const W = 640;
const H = 170;
const PAD = { top: 8, right: 4, bottom: 22, left: 30 };

/** Stacked log volume per minute for the last hour. */
export default function SignalChart({ timeline = [] }) {
  const [hover, setHover] = useState(null);
  const totals = timeline.map((m) => ORDER.reduce((s, l) => s + m[l], 0));
  const max = Math.max(4, ...totals);
  const step = Math.ceil(max / 4);
  const top = step * 4;
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const colW = innerW / Math.max(timeline.length, 1);
  const y = (v) => PAD.top + innerH - (v / top) * innerH;
  const shown = hover !== null ? timeline[hover] : null;

  return (
    <div>
      <div className="chart-tip" aria-live="polite">
        {shown
          ? `${clock(shown.minute).slice(0, 5)}  ${ORDER.slice().reverse().map((l) => `${shown[l]} ${l.toLowerCase()}`).join(", ")}`
          : "Hover a bar to see that minute."}
      </div>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img"
        aria-label={`Log lines per minute over the last hour, peak ${Math.max(0, ...totals)} lines`}
        onMouseLeave={() => setHover(null)}>
        {[0, 1, 2, 3, 4].map((i) => (
          <g key={i}>
            <line className="grid-line" x1={PAD.left} x2={W - PAD.right} y1={y(i * step)} y2={y(i * step)} />
            <text className="axis" x={PAD.left - 6} y={y(i * step) + 4} textAnchor="end">{i * step}</text>
          </g>
        ))}
        {timeline.map((m, i) => {
          let acc = 0;
          const x = PAD.left + i * colW;
          return (
            <g key={m.minute}>
              {ORDER.map((level) => {
                if (!m[level]) return null;
                const y1 = y(acc + m[level]);
                const h = y(acc) - y1;
                acc += m[level];
                return <rect key={level} className={`bar-${level}`} x={x + 1} y={y1} width={Math.max(colW - 2, 1)} height={h} rx="1" />;
              })}
              <rect className="hover-col" x={x} y={PAD.top} width={colW} height={innerH} onMouseEnter={() => setHover(i)} />
              {i % 15 === 0 && <text className="axis" x={x} y={H - 6}>{clock(m.minute).slice(0, 5)}</text>}
            </g>
          );
        })}
        {timeline.length > 0 && <text className="axis" x={W - PAD.right} y={H - 6} textAnchor="end">now</text>}
      </svg>
      <div className="legend" aria-hidden="true">
        {ORDER.slice().reverse().map((l) => (
          <span key={l}><i className={`sw-${l}`} />{l.toLowerCase()}</span>
        ))}
      </div>
    </div>
  );
}
