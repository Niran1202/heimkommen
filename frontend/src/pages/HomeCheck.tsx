import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, type HomeCheck } from '../api/client'
import { JourneyCard } from '../components/JourneyCard'
import { pct } from '../components/RiskBadge'
import { useAuth } from '../hooks/useAuth'

export function HomeCheckPage() {
  const [params] = useSearchParams()
  const { loggedIn } = useAuth()
  const [data, setData] = useState<HomeCheck | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [saved, setSaved] = useState('')

  const from = params.get('from') ?? ''
  const to = params.get('to') ?? ''
  const after = params.get('after') ?? ''
  const date = params.get('date') ?? undefined
  const regional = params.get('regional') !== '0'

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    api.homeCheck({ from, to, after, date, regional_only: regional })
      .then((r) => !cancelled && setData(r))
      .catch((e: Error) => !cancelled && (setError(e.message), setData(null)))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [from, to, after, date, regional])

  const save = async () => {
    if (!data) return
    try {
      await api.saveTrip({ from_station_id: data.origin.id, to_station_id: data.destination.id, usual_departure: after, regional_only: regional })
      setSaved('Saved to My trips.')
    } catch (e) {
      setSaved((e as Error).message)
    }
  }

  return (
    <>
      <p className="back"><Link to="/">← New search</Link></p>
      {loading && <div className="panel loading" aria-live="polite">Planning and simulating 2,000 evenings…</div>}
      {error && <p role="alert" className="error-message">{error}</p>}
      {data && !loading && (
        <>
          <section className="panel summary">
            <h1>{data.origin.name} → {data.destination.name}</h1>
            <p className="muted">
              {new Date(`${data.service_date}T12:00`).toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })}
              {' '}· after {data.after}{data.regional_only ? ' · Deutschlandticket' : ''}
            </p>
            <div className="summary-grid">
              <div>
                <span className="muted small">Latest safe departure ({pct(data.confidence)} sure)</span>
                <strong className="big">{data.latest_safe_departure?.departure ?? '–'}</strong>
                {data.latest_safe_departure && <span className="small">arrives {data.latest_safe_departure.arrival}</span>}
              </div>
              <div>
                <span className="muted small">Last connection tonight</span>
                <strong className="big">{data.last_connection?.departure ?? '–'}</strong>
                {data.last_connection && (
                  <span className="small">{pct(data.last_connection.p_home)} chance you get home</span>
                )}
              </div>
            </div>
            {!data.latest_safe_departure && data.journeys.length > 0 && (
              <p className="warning small">No departure tonight reaches the {pct(data.confidence)} safety level. Leave as early as you can.</p>
            )}
            {saved && <p className="muted small">{saved}</p>}
          </section>

          {data.journeys.length === 0 && (
            <p className="empty-message">No connection found for the rest of this service day.</p>
          )}
          {data.journeys.map((journey, i) => (
            <JourneyCard key={journey.id} journey={journey}
              highlight={journey.id === data.latest_safe_departure?.journey_id ? 'Latest safe' : i === 0 ? 'Next' : undefined}
              onSave={loggedIn ? save : undefined} />
          ))}
          <ul className="notes">
            {data.notes.map((note) => <li key={note} className="muted small">{note}</li>)}
            <li className="muted small">Model {data.model_version}. Probabilities are estimates, not guarantees.</li>
          </ul>
        </>
      )}
    </>
  )
}
