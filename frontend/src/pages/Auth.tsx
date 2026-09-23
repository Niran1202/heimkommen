import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

export function AuthPage({ mode }: { mode: 'login' | 'register' }) {
  const auth = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await (mode === 'login' ? auth.login(email, password) : auth.register(email, password))
      navigate('/trips')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="panel auth-form" onSubmit={submit}>
      <h1>{mode === 'login' ? 'Log in' : 'Create an account'}</h1>
      <p className="muted small">
        An account only stores your email and the trips you save. You can delete everything at any time.
      </p>
      <div className="field">
        <label htmlFor="email">Email</label>
        <input id="email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
      </div>
      <div className="field">
        <label htmlFor="password">Password {mode === 'register' && <span className="muted">(at least 8 characters)</span>}</label>
        <input id="password" type="password" minLength={8} autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
          value={password} onChange={(e) => setPassword(e.target.value)} required />
      </div>
      {error && <p role="alert" className="error-message small">{error}</p>}
      <button className="primary" type="submit" disabled={busy}>{mode === 'login' ? 'Log in' : 'Create account'}</button>
      <p className="small">
        {mode === 'login' ? <>No account yet? <Link to="/register">Create one</Link></> : <>Already registered? <Link to="/login">Log in</Link></>}
      </p>
    </form>
  )
}
