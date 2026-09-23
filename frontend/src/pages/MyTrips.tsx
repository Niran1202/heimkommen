import { useEffect, useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { api, type SavedTrip } from '../api/client'
import { StationInput } from '../components/StationInput'
import { useAuth } from '../hooks/useAuth'
import { nowHHMM, todayISO } from './Home'

export function MyTripsPage() {
  const auth = useAuth()
  const navigate = useNavigate()
  const [trips, setTrips] = useState<SavedTrip[]>([])
  const [label, setLabel] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [usual, setUsual] = useState('18:00')
  const [error, setError] = useState('')

  useEffect(() => {
    if (auth.loggedIn) api.trips().then(setTrips).catch((e: Error) => setError(e.message))
  }, [auth.loggedIn])

  if (!auth.loggedIn) return <Navigate to="/login" replace />

  const add = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    try {
      const trip = await api.saveTrip({ label: label || null, from_station_id: from, to_station_id: to, usual_departure: usual, regional_only: true })
      setTrips((t) => [trip, ...t])
      setLabel('')
      setFrom('')
      setTo('')
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const remove = async (id: number) => {
    await api.deleteTrip(id)
    setTrips((t) => t.filter((x) => x.id !== id))
  }

  const deleteAccount = async () => {
    if (!window.confirm('Delete your account and all saved trips? This cannot be undone.')) return
    await auth.deleteAccount()
    navigate('/')
  }

  return (
    <>
      <section className="hero">
        <h1>My trips</h1>
        <p className="subtitle">Logged in as {auth.email ?? '…'}</p>
      </section>

      <section className="panel">
        {trips.length === 0 && <p className="muted">No saved trips yet.</p>}
        <ul className="trip-list">
          {trips.map((t) => (
            <li key={t.id}>
              <Link to={`/check?${new URLSearchParams({
                from: t.from_station_id, to: t.to_station_id, after: t.usual_departure ?? nowHHMM(), date: todayISO(),
                regional: t.regional_only ? '1' : '0',
              })}`}>
                {t.label ? <strong>{t.label}: </strong> : null}{t.from_station_name} → {t.to_station_name}
                {t.usual_departure ? ` · ${t.usual_departure}` : ''}
              </Link>
              <button type="button" className="link-button" onClick={() => remove(t.id)} aria-label={`Delete ${t.label ?? 'trip'}`}>
                Delete
              </button>
            </li>
          ))}
        </ul>
      </section>

      <form className="panel search-form" onSubmit={add}>
        <h2>Add a trip</h2>
        <div className="field">
          <label htmlFor="label">Name (optional)</label>
          <input id="label" value={label} maxLength={80} onChange={(e) => setLabel(e.target.value)} placeholder="Home from work" />
        </div>
        <StationInput label="From" value={from} onChange={setFrom} />
        <StationInput label="To" value={to} onChange={setTo} />
        <div className="field">
          <label htmlFor="usual">Usual departure</label>
          <input id="usual" type="time" value={usual} onChange={(e) => setUsual(e.target.value)} />
        </div>
        {error && <p role="alert" className="error-message small">{error}</p>}
        <button type="submit" className="primary" disabled={from.length < 2 || to.length < 2}>Save trip</button>
      </form>

      <section className="panel danger">
        <h2>Your data</h2>
        <p className="small">Deleting your account removes your email, password hash and every saved trip immediately.</p>
        <div className="card-actions">
          <button type="button" className="secondary" onClick={auth.logout}>Log out</button>
          <button type="button" className="danger-button" onClick={deleteAccount}>Delete account</button>
        </div>
      </section>
    </>
  )
}
