import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, type SavedTrip } from '../api/client'
import { StationInput } from '../components/StationInput'
import { useAuth } from '../hooks/useAuth'

export function nowHHMM(): string {
  const d = new Date()
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export function todayISO(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function useNearestStation(setValue: (name: string) => void) {
  const [locating, setLocating] = useState(false)
  const [error, setError] = useState('')
  const locate = () => {
    if (!navigator.geolocation) {
      setError('Your browser cannot share its location.')
      return
    }
    setLocating(true)
    setError('')
    navigator.geolocation.getCurrentPosition(
      async (position) => {
        try {
          const result = await api.nearbyStations(position.coords.latitude, position.coords.longitude)
          if (result.stations[0]) setValue(result.stations[0].name)
        } catch (e) {
          setError((e as Error).message)
        } finally {
          setLocating(false)
        }
      },
      () => {
        setError('Location permission was denied.')
        setLocating(false)
      },
      { timeout: 10000, maximumAge: 60000 },
    )
  }
  return { locate, locating, error }
}

export function HomePage() {
  const navigate = useNavigate()
  const { loggedIn } = useAuth()
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('Villingen Bahnhof/ZOB')
  const [after, setAfter] = useState(nowHHMM())
  const [date, setDate] = useState(todayISO())
  const [regionalOnly, setRegionalOnly] = useState(true)
  const [trips, setTrips] = useState<SavedTrip[]>([])
  const nearest = useNearestStation(setFrom)

  useEffect(() => {
    if (loggedIn) api.trips().then(setTrips).catch(() => setTrips([]))
  }, [loggedIn])

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const params = new URLSearchParams({ from, to, after, date, regional: regionalOnly ? '1' : '0' })
    navigate(`/check?${params}`)
  }

  return (
    <>
      <section className="hero">
        <h1>Will I get home tonight?</h1>
        <p className="subtitle">
          Heimkommen plans your trip back to the Schwarzwald-Baar-Heuberg region and tells you how likely each connection is
          to work, based on months of real delay data, plus what to do if it doesn't.
        </p>
      </section>

      <form className="panel search-form" onSubmit={submit}>
        <StationInput label="From" value={from} onChange={setFrom} placeholder="e.g. Stuttgart Hbf"
          onLocate={nearest.locate} locating={nearest.locating} />
        <StationInput label="To" value={to} onChange={setTo} placeholder="e.g. Villingen" />
        <div className="field-row">
          <div className="field">
            <label htmlFor="after">Leave after</label>
            <input id="after" type="time" value={after} onChange={(e) => setAfter(e.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="date">Date</label>
            <input id="date" type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
          </div>
        </div>
        <label className="checkbox">
          <input type="checkbox" checked={regionalOnly} onChange={(e) => setRegionalOnly(e.target.checked)} />
          Deutschlandticket only (no ICE/IC/EC)
        </label>
        {nearest.error && <p className="error-message small">{nearest.error}</p>}
        <button type="submit" className="primary" disabled={from.trim().length < 2 || to.trim().length < 2}>
          Check my way home
        </button>
      </form>

      {trips.length > 0 && (
        <section className="panel">
          <h2>Your saved trips</h2>
          <ul className="trip-list">
            {trips.map((t) => (
              <li key={t.id}>
                <Link to={`/check?${new URLSearchParams({
                  from: t.from_station_id, to: t.to_station_id, after: t.usual_departure ?? nowHHMM(),
                  date: todayISO(), regional: t.regional_only ? '1' : '0',
                })}`}>
                  {t.label ? `${t.label}: ` : ''}{t.from_station_name} → {t.to_station_name}
                  {t.usual_departure ? ` · ${t.usual_departure}` : ''}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="panel how">
        <h2>How it works</h2>
        <ol>
          <li><strong>Routing:</strong> a RAPTOR planner over the official NVBW timetable for Baden-Württemberg.</li>
          <li><strong>Delays:</strong> a LightGBM model trained on months of real arrival and departure times.</li>
          <li><strong>Simulation:</strong> 2,000 simulated evenings per journey. Missed a connection? It takes the next one, or you're stranded.</li>
        </ol>
        <p className="muted small">Want to arrive by a certain time instead? Use the <Link to="/deadline">deadline planner</Link>.</p>
      </section>
    </>
  )
}
