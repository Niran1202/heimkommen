import { lazy, Suspense, useState } from 'react'
import { api, type Journey, type LiveJourney } from '../api/client'
import { levelForMiss, Meter, pct, RiskBadge } from './RiskBadge'

// Leaflet is only downloaded when a map is opened.
const JourneyMap = lazy(() => import('./JourneyMap').then((m) => ({ default: m.JourneyMap })))

type Props = {
  journey: Journey
  highlight?: string
  onSave?: () => void
}

export function JourneyCard({ journey, highlight, onSave }: Props) {
  const [showMap, setShowMap] = useState(false)
  const [live, setLive] = useState<LiveJourney | null>(null)
  const [liveError, setLiveError] = useState('')
  const [loadingLive, setLoadingLive] = useState(false)
  const { risk } = journey
  const weak = journey.weak_point?.index

  const loadLive = async () => {
    setLoadingLive(true)
    setLiveError('')
    try {
      setLive(await api.live(journey.id))
    } catch (e) {
      setLiveError((e as Error).message)
    } finally {
      setLoadingLive(false)
    }
  }

  return (
    <article className="journey-card">
      <header className="journey-header">
        <div>
          <p className="journey-times">
            <strong>{journey.departure}</strong> → <strong>{journey.arrival}</strong>
          </p>
          <p className="muted">
            {journey.duration_minutes} min · {journey.transfers === 0 ? 'direct' : `${journey.transfers} change${journey.transfers > 1 ? 's' : ''}`}
            {highlight && <span className="pill">{highlight}</span>}
          </p>
        </div>
        <RiskBadge level={risk.level} />
      </header>

      <div className="meters">
        <Meter label="Home tonight" value={risk.p_home} hint="Probability to reach the destination tonight, including Plan B" />
        {journey.transfers > 0 && (
          <Meter label="Connections work" value={risk.p_connections} hint="Probability that every planned change works" />
        )}
        <Meter label="On time (≤5 min late)" value={risk.p_on_time} />
      </div>
      <p className="muted small">
        Likely arrival {risk.arrival_p50 ?? '–'}
        {risk.arrival_p90 ? `, 9 in 10 times by ${risk.arrival_p90}` : ', but a real chance of not arriving tonight'}.
      </p>

      <ol className="timeline">
        {journey.legs.map((leg, i) => {
          const connection = journey.connections[i]
          const missLevel = levelForMiss(connection?.p_miss ?? 0)
          return (
            <li key={`${leg.route}-${i}`}>
              {i > 0 && connection && (
                <div className={`transfer ${weak === i ? `weak weak-${missLevel}` : ''}`}>
                  <span className={`dot risk-${missLevel}`} aria-hidden="true" />
                  <div>
                    <p>
                      Change at <strong>{connection.station}</strong> · {connection.planned_buffer_minutes} min
                      {weak === i && <span className="pill warn">Weak point</span>}
                    </p>
                    <p className="muted small">Missed in {pct(connection.p_miss)} of simulations</p>
                    {connection.plan_b && (
                      <p className="plan-b small">
                        Plan B: {connection.plan_b.summary}, arrives {connection.plan_b.arrival}
                      </p>
                    )}
                  </div>
                </div>
              )}
              <div className="leg">
                <span className={`route-chip cat-${leg.category.toLowerCase()}`}>{leg.route}</span>
                <div className="leg-body">
                  <p>
                    <strong>{leg.departure}</strong> {leg.origin.name}
                    {leg.origin.platform && <span className="muted"> · {leg.origin.platform}</span>}
                  </p>
                  <p>
                    <strong>{leg.arrival}</strong> {leg.destination.name}
                    {leg.destination.platform && <span className="muted"> · {leg.destination.platform}</span>}
                  </p>
                  <p className="muted small">
                    {leg.risk.modelled
                      ? `Typical delay ${Math.round(leg.risk.arrival_delay_p50)} min, 1 in 10 trains ≥ ${Math.round(leg.risk.arrival_delay_p90)} min · cancelled ${pct(leg.risk.p_cancel)}`
                      : 'Bus/tram – assumed on time'}
                    {leg.headsign && ` · towards ${leg.headsign}`}
                  </p>
                </div>
              </div>
            </li>
          )
        })}
      </ol>

      {journey.connections[0]?.plan_b && (
        <p className="plan-b small">If you miss the first train: {journey.connections[0].plan_b.summary}</p>
      )}

      <div className="card-actions">
        <button type="button" className="secondary" onClick={() => setShowMap((v) => !v)}>
          {showMap ? 'Hide map' : 'Show map'}
        </button>
        <button type="button" className="secondary" onClick={loadLive} disabled={loadingLive}>
          {loadingLive ? 'Loading…' : 'Live status'}
        </button>
        {onSave && <button type="button" className="secondary" onClick={onSave}>Save trip</button>}
      </div>

      {liveError && <p className="error-message small">{liveError}</p>}
      {live && (
        <div className="live">
          {!live.available && <p className="muted small">Live data unavailable: {live.notes.join(' ')}</p>}
          {live.legs.map((stop) => (
            <p key={`${stop.train}-${stop.station}`} className="small">
              <strong>{stop.train}</strong> at {stop.station}: planned {stop.planned_departure}
              {stop.cancelled ? ' — cancelled' : stop.expected_departure ? `, expected ${stop.expected_departure}` : ''}
              {stop.delay_minutes ? ` (+${stop.delay_minutes})` : ''}
              {stop.platform ? `, platform ${stop.platform}` : ''}
            </p>
          ))}
          {live.available && live.notes.map((n) => <p key={n} className="muted small">{n}</p>)}
        </div>
      )}

      {showMap && (
        <Suspense fallback={<div className="journey-map" />}>
          <JourneyMap journey={journey} />
        </Suspense>
      )}
    </article>
  )
}
