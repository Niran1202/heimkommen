import { useEffect, useState } from 'react'
import { api, type AccuracyResponse } from '../api/client'
import { CalibrationChart } from '../components/CalibrationChart'
import { pct } from '../components/RiskBadge'

const TARGETS: Record<string, string> = {
  held: 'All connections work',
  on_time: 'Arrive ≤ 5 min late',
  stranded: 'Stranded',
}

export function AccuracyPage() {
  const [data, setData] = useState<AccuracyResponse | null>(null)
  const [period, setPeriod] = useState('30d')
  const [error, setError] = useState('')

  useEffect(() => {
    api.accuracy(period).then(setData).catch((e: Error) => setError(e.message))
  }, [period])

  const replay = data?.offline.replay
  const model = data?.offline.model
  const live = data?.live

  return (
    <>
      <section className="hero">
        <h1>How good are the predictions?</h1>
        <p className="subtitle">
          Every prediction is checked against what actually happened. A forecast of 70% should come true about 7 times in 10.
        </p>
      </section>
      {error && <p role="alert" className="error-message">{error}</p>}

      {replay && (
        <section className="panel">
          <h2>Historical replay ({replay.months.join(', ')})</h2>
          <p className="muted small">
            {replay.journeys} real evening journeys, planned with the timetable and scored against real train times. The
            model never saw these months during training.
          </p>
          <table className="data-table">
            <thead>
              <tr><th>Brier score (lower is better)</th><th>Timetable only</th><th>Historical median</th><th>Simulator</th></tr>
            </thead>
            <tbody>
              {Object.entries(TARGETS).map(([key, label]) => {
                const row = replay.brier[key]
                if (!row) return null
                return (
                  <tr key={key}>
                    <td>{label} <span className="muted">(happened {pct(row.observed_rate)})</span></td>
                    <td>{row.timetable_only.toFixed(3)}</td>
                    <td>{row.historical_median.toFixed(3)}</td>
                    <td><strong>{row.simulator.toFixed(3)}</strong></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <CalibrationChart title="Predicted vs. observed (replay)" series={[
            { key: 'on_time', label: 'Arrive ≤ 5 min late', slot: 1, bins: replay.calibration.on_time },
            { key: 'held', label: 'All connections work', slot: 2, bins: replay.calibration.held },
          ]} />
          <h3>Where it is weaker</h3>
          <table className="data-table">
            <thead><tr><th>Shortest change</th><th>Journeys</th><th>Predicted to work</th><th>Actually worked</th></tr></thead>
            <tbody>
              {replay.by_buffer.map((b) => (
                <tr key={b.buffer}><td>{b.buffer}</td><td>{b.journeys}</td><td>{pct(b.predicted_held)}</td><td>{pct(b.observed_held)}</td></tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">
            The simulator is somewhat optimistic about connections, most of all for tight changes. Treat a
            predicted 40% on a 5-minute change as closer to 30%.
          </p>
        </section>
      )}

      <section className="panel">
        <div className="panel-head">
          <h2>Live: predictions made on this site</h2>
          <select value={period} onChange={(e) => setPeriod(e.target.value)} aria-label="Period">
            <option value="7d">Last 7 days</option>
            <option value="30d">Last 30 days</option>
            <option value="90d">Last 90 days</option>
          </select>
        </div>
        {live && live.matched_predictions === 0 && (
          <p className="muted">No matched predictions yet. The nightly job compares yesterday's predictions with real train times.</p>
        )}
        {live && live.matched_predictions > 0 && live.brier && (
          <>
            <p className="muted small">{live.matched_predictions} predictions matched with outcomes.</p>
            <table className="data-table">
              <thead><tr><th>Brier score</th><th>Timetable only</th><th>Simulator</th></tr></thead>
              <tbody>
                <tr><td>All connections work</td><td>{live.brier.timetable_only_connections?.toFixed(3)}</td><td><strong>{live.brier.connections?.toFixed(3)}</strong></td></tr>
                <tr><td>Arrive ≤ 5 min late</td><td>{live.brier.timetable_only_on_time?.toFixed(3)}</td><td><strong>{live.brier.on_time?.toFixed(3)}</strong></td></tr>
              </tbody>
            </table>
            <CalibrationChart title="Predicted vs. observed (live)" series={[
              { key: 'on_time', label: 'Arrive ≤ 5 min late', slot: 1, bins: live.calibration_on_time ?? [] },
              { key: 'held', label: 'All connections work', slot: 2, bins: live.calibration_connections ?? [] },
            ]} />
          </>
        )}
      </section>

      {model && (
        <section className="panel">
          <h2>Delay model {model.version}</h2>
          <p className="muted small">
            Trained on {model.train_months.join(', ')} ({model.n_train.toLocaleString()} events), tested on{' '}
            {model.test_months.join(', ')} ({model.n_test.toLocaleString()} events).
          </p>
          <table className="data-table">
            <thead><tr><th>Mean quantile loss</th><th>Value</th></tr></thead>
            <tbody>
              <tr><td>LightGBM (planning mode)</td><td><strong>{model.mean_pinball.model_plan.toFixed(3)}</strong></td></tr>
              <tr><td>Historical quantiles per line and station</td><td>{model.mean_pinball.baseline_hist_quantiles.toFixed(3)}</td></tr>
              <tr><td>Historical median</td><td>{model.mean_pinball.baseline_hist_median.toFixed(3)}</td></tr>
            </tbody>
          </table>
          <p className="muted small">
            Coverage of the 90th percentile: {pct(model.coverage['0.90'])} of delays fell below it (target 90%).
          </p>
        </section>
      )}
    </>
  )
}
