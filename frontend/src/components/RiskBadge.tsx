type Level = 'low' | 'medium' | 'high'

const LABELS: Record<Level, { icon: string; text: string }> = {
  low: { icon: '✓', text: 'Low risk' },
  medium: { icon: '!', text: 'Some risk' },
  high: { icon: '✕', text: 'High risk' },
}

/** Status is never color alone: icon + text label always accompany the color. */
export function RiskBadge({ level }: { level: string }) {
  const key = (level in LABELS ? level : 'medium') as Level
  return (
    <span className={`risk-badge risk-${key}`}>
      <span aria-hidden="true" className="risk-icon">{LABELS[key].icon}</span>
      {LABELS[key].text}
    </span>
  )
}

export function levelForMiss(p: number): Level {
  if (p < 0.1) return 'low'
  if (p < 0.3) return 'medium'
  return 'high'
}

export function pct(value: number | null | undefined): string {
  if (value === null || value === undefined) return '–'
  if (value > 0 && value < 0.01) return '<1%'
  if (value < 1 && value > 0.99) return '>99%'
  return `${Math.round(value * 100)}%`
}

/** Horizontal meter for a probability; the number is always printed next to it. */
export function Meter({ label, value, hint }: { label: string; value: number; hint?: string }) {
  const level = value >= 0.9 ? 'low' : value >= 0.7 ? 'medium' : 'high'
  return (
    <div className="meter" title={hint}>
      <div className="meter-head">
        <span>{label}</span>
        <strong>{pct(value)}</strong>
      </div>
      <div className="meter-track" role="presentation">
        <div className={`meter-fill risk-${level}`} style={{ width: `${Math.max(2, value * 100)}%` }} />
      </div>
    </div>
  )
}
