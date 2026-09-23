import { useState } from 'react'
import type { CalibrationBin } from '../api/client'

type Series = { key: string; label: string; slot: 1 | 2; bins: CalibrationBin[] }

const W = 360
const H = 320
const M = { top: 12, right: 12, bottom: 40, left: 44 }
const iw = W - M.left - M.right
const ih = H - M.top - M.bottom
const x = (v: number) => M.left + v * iw
const y = (v: number) => M.top + (1 - v) * ih
const observed = (b: CalibrationBin) => b.observed ?? b.observed_rate ?? 0

/** Reliability diagram: predicted probability vs. observed frequency, marker area ~ journeys. */
export function CalibrationChart({ series, title }: { series: Series[]; title: string }) {
  const [hover, setHover] = useState<{ s: Series; b: CalibrationBin } | null>(null)
  const [showTable, setShowTable] = useState(false)
  const maxCount = Math.max(1, ...series.flatMap((s) => s.bins.map((b) => b.count)))
  const ticks = [0, 0.25, 0.5, 0.75, 1]

  return (
    <figure className="viz-root chart">
      <figcaption>
        <strong>{title}</strong>
        <div className="legend">
          <span><i className="swatch line-dashed" /> Perfect calibration</span>
          {series.map((s) => (
            <span key={s.key}><i className={`swatch series-${s.slot}`} /> {s.label}</span>
          ))}
        </div>
      </figcaption>
      <div className="chart-wrap">
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={title}>
          {ticks.map((t) => (
            <g key={t}>
              <line className="grid" x1={x(0)} x2={x(1)} y1={y(t)} y2={y(t)} />
              <line className="grid" x1={x(t)} x2={x(t)} y1={y(0)} y2={y(1)} />
              <text className="tick" x={x(0) - 8} y={y(t) + 4} textAnchor="end">{t * 100}%</text>
              <text className="tick" x={x(t)} y={y(0) + 16} textAnchor="middle">{t * 100}%</text>
            </g>
          ))}
          <line className="axis" x1={x(0)} x2={x(1)} y1={y(0)} y2={y(0)} />
          <line className="diagonal" x1={x(0)} y1={y(0)} x2={x(1)} y2={y(1)} />
          <text className="axis-label" x={x(0.5)} y={H - 6} textAnchor="middle">Predicted probability</text>
          <text className="axis-label" transform={`translate(12 ${y(0.5)}) rotate(-90)`} textAnchor="middle">Observed</text>
          {series.map((s) => (
            <g key={s.key} className={`series-${s.slot}`}>
              <polyline className="series-line" fill="none"
                points={s.bins.map((b) => `${x(b.mean_predicted)},${y(observed(b))}`).join(' ')} />
              {s.bins.map((b) => {
                const r = 4 + 8 * Math.sqrt(b.count / maxCount)
                return (
                  <g key={`${s.key}-${b.mean_predicted}`}>
                    <circle className="series-dot" cx={x(b.mean_predicted)} cy={y(observed(b))} r={r} />
                    {/* Larger invisible hit target than the mark */}
                    <circle cx={x(b.mean_predicted)} cy={y(observed(b))} r={Math.max(r, 14)} fill="transparent"
                      onMouseEnter={() => setHover({ s, b })} onMouseLeave={() => setHover(null)}
                      onFocus={() => setHover({ s, b })} onBlur={() => setHover(null)} tabIndex={0} />
                  </g>
                )
              })}
            </g>
          ))}
        </svg>
        {hover && (
          <div className="tooltip" style={{
            left: `${(x(hover.b.mean_predicted) / W) * 100}%`,
            top: `${(y(observed(hover.b)) / H) * 100}%`,
          }}>
            <strong>{hover.s.label}</strong>
            <span>Predicted {Math.round(hover.b.mean_predicted * 100)}%</span>
            <span>Observed {Math.round(observed(hover.b) * 100)}%</span>
            <span>{hover.b.count} journeys</span>
          </div>
        )}
      </div>
      <button type="button" className="link-button small" onClick={() => setShowTable((v) => !v)}>
        {showTable ? 'Hide table' : 'Show as table'}
      </button>
      {showTable && (
        <table className="data-table">
          <thead><tr><th>Series</th><th>Predicted</th><th>Observed</th><th>Journeys</th></tr></thead>
          <tbody>
            {series.flatMap((s) => s.bins.map((b) => (
              <tr key={`${s.key}-${b.mean_predicted}`}>
                <td>{s.label}</td>
                <td>{(b.mean_predicted * 100).toFixed(0)}%</td>
                <td>{(observed(b) * 100).toFixed(0)}%</td>
                <td>{b.count}</td>
              </tr>
            )))}
          </tbody>
        </table>
      )}
    </figure>
  )
}
