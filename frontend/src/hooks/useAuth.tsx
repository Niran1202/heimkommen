import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, getToken, setToken } from '../api/client'

type AuthState = {
  /** False in the desktop app, which is single-user and has no login. */
  accountsEnabled: boolean
  email: string | null
  loggedIn: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string) => Promise<void>
  logout: () => void
  deleteAccount: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [email, setEmail] = useState<string | null>(null)
  const [loggedIn, setLoggedIn] = useState(() => Boolean(getToken()))
  const [accountsEnabled, setAccountsEnabled] = useState(true)

  useEffect(() => {
    api.health().then((h) => {
      if (h.accounts_enabled === false) {
        setAccountsEnabled(false)
        setLoggedIn(false)
      }
    }).catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!loggedIn || !accountsEnabled) return
    api.me().then((me) => setEmail(me.email)).catch(() => {
      setToken(null)
      setLoggedIn(false)
    })
  }, [loggedIn, accountsEnabled])

  const finish = useCallback((token: string, mail: string) => {
    setToken(token)
    setEmail(mail.toLowerCase())
    setLoggedIn(true)
  }, [])

  const value = useMemo<AuthState>(() => ({
    accountsEnabled,
    email,
    loggedIn,
    login: async (mail, password) => finish((await api.login(mail, password)).access_token, mail),
    register: async (mail, password) => finish((await api.register(mail, password)).access_token, mail),
    logout: () => {
      setToken(null)
      setEmail(null)
      setLoggedIn(false)
    },
    deleteAccount: async () => {
      await api.deleteAccount()
      setToken(null)
      setEmail(null)
      setLoggedIn(false)
    },
  }), [accountsEnabled, email, loggedIn, finish])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside <AuthProvider>')
  return context
}
