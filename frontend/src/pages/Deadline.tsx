import { useState, type FormEvent } from 'react'
import { api, type Deadline } from '../api/client'
import { JourneyCard } from '../components/JourneyCard'
import { pct } from '../components/RiskBadge'
import { StationInput } from '../components/StationInput'
import { todayISO, useNearestStation } from './Home'

export function DeadlinePage() {
  const [from, setFrom] = useState('Villingen Bahnhof/ZOB')
  const [to, setTo] = useState('')
  const [arriveBy, setArriveBy] = useState('09:00')
  const [date, setDate] = useState(todayISO())
  const [confidence, setConfidence] = useState(0.9)
  const [regionalOnly, setRegionalOnly] = useState(true)
  const [data, setData] = useState<Deadline | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const nearest = useNearestStation(setFrom)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setLoading(true)
    setError('')
    try {
      setData(await api.deadline({ from, to, arrive_by: arriveBy, date, confidence, regional_only: regionalOnly }))
    } catch (e) {
      setError((e as Error).message)
      setData(null)
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <section className="hero">
        <h1>I need to be there by…</h1>
        <p className="subtitle">Find the latest departure that still gets you there on time with the certainty you choose.</p>
      </section>
      <form className="panel search-form" onSubmit={submit}>
        <StationInput label="From" value={from} onChange={setFrom} onLocate={nearest.locate} locating={nearest.locating} />
        <StationInput label="To" value={to} onChange={setTo} placeholder="e.g. Freiburg Hbf" />
        <div className="field-row">
          <div className="field">
            <label htmlFor="arrive">Arrive by</label>
            <input id="arrive" type="time" value={arriveBy} onChange={(e) => setArriveBy(e.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="ddate">Date</label>
            <input id="ddate" type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
          </div>
        </div>
        <div className="field">
          <label htmlFor="confidence">How sure do you need to be? <strong>{pct(confidence)}</strong></label>
          <input id="confidence" type="range" min={0.5} max={0.99} step={0.01} value={confidence}
            onChange={(e) => setConfidence(Number(e.target.value))} />
        </div>
        <label className="checkbox">
          <input type="checkbox" checked={regionalOnly} onChange={(e) => setRegionalOnly(e.target.checked)} />
          Deutschlandticket only
        </label>
        {nearest.error && <p className="error-message small">{nearest.error}</p>}
        <button type="submit" className="primary" disabled={loading || from.length < 2 || to.length < 2}>
          {loading ? 'Simulating…' : 'Find latest departure'}
        </button>
      </form>

      {error && <p role="alert" className="error-message">{error}</p>}
      {data && (
        <>
          <section className="panel summary">
            {data.recommended ? (
              <p>
                Leave at <strong className="big inline">{data.recommended.departure}</strong> to arrive by {data.arrive_by} with
                {' '}{pct(data.p_arrive_by)} probability.
              </p>
            ) : (
              <p className="warning">No departure makes it by {data.arrive_by} with {pct(data.confidence)} certainty.</p>
            )}
            {data.checked.length > 0 && (
              <table className="data-table">
                <thead><tr><th>Departure</th><th>Planned arrival</th><th>Arrives in time</th></tr></thead>
                <tbody>
                  {data.checked.map((c) => (
                    <tr key={c.departure}><td>{c.departure}</td><td>{c.arrival}</td><td>{pct(c.p_arrive_by)}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
          {data.recommended && <JourneyCard journey={data.recommended} highlight="Recommended" />}
          <ul className="notes">{data.notes.map((n) => <li key={n} className="muted small">{n}</li>)}</ul>
        </>
      )}
    </>
  )
}
