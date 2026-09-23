import type { components } from './schema'

export type Station = components['schemas']['StationOut']
export type HomeCheck = components['schemas']['HomeCheckResponse']
export type Deadline = components['schemas']['DeadlineResponse']
export type Journey = components['schemas']['JourneyOut']
export type Leg = components['schemas']['LegOut']
export type Connection = components['schemas']['TransferOut']
export type LiveJourney = components['schemas']['LiveJourneyResponse']
export type SavedTrip = components['schemas']['SavedTripOut']
export type SavedTripIn = components['schemas']['SavedTripIn']

// Same origin in production (Caddy proxies /api); Vite proxies /api in development.
const BASE = import.meta.env.VITE_API_URL ?? ''
const TOKEN_KEY = 'heimkommen.token'

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* storage unavailable (private mode): the session just won't persist */
  }
}

async function request<T>(path: string, init: RequestInit = {}, auth = false): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body) headers.set('Content-Type', 'application/json')
  const token = getToken()
  if (auth && token) headers.set('Authorization', `Bearer ${token}`)
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, { ...init, headers })
  } catch {
    throw new ApiError(0, 'The Heimkommen server is not reachable. Check your connection and try again.')
  }
  if (response.status === 204) return undefined as T
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = body?.detail
    const message = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((d) => d.msg).join(', ') : response.statusText
    throw new ApiError(response.status, message || 'Request failed')
  }
  return body as T
}

function query(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  }
  return search.toString()
}

export const api = {
  searchStations: (search: string, signal?: AbortSignal) =>
    request<components['schemas']['StationsResponse']>(`/api/v1/stations?${query({ search, limit: 8 })}`, { signal }),
  nearbyStations: (lat: number, lon: number) =>
    request<components['schemas']['StationsResponse']>(`/api/v1/stations/nearby?${query({ lat, lon, limit: 5 })}`),
  homeCheck: (p: { from: string; to: string; after: string; date?: string; regional_only?: boolean }) =>
    request<HomeCheck>(`/api/v1/journeys/home-check?${query(p)}`),
  deadline: (p: { from: string; to: string; arrive_by: string; date?: string; confidence?: number; regional_only?: boolean }) =>
    request<Deadline>(`/api/v1/journeys/deadline?${query(p)}`),
  live: (journeyId: string) => request<LiveJourney>(`/api/v1/journeys/${journeyId}/live`),
  accuracy: (period = '30d') => request<AccuracyResponse>(`/api/v1/accuracy?${query({ period })}`),
  register: (email: string, password: string) =>
    request<components['schemas']['TokenOut']>('/api/v1/auth/register', { method: 'POST', body: JSON.stringify({ email, password }) }),
  login: (email: string, password: string) =>
    request<components['schemas']['TokenOut']>('/api/v1/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  me: () => request<components['schemas']['UserOut']>('/api/v1/me', {}, true),
  deleteAccount: () => request<void>('/api/v1/me', { method: 'DELETE' }, true),
  trips: () => request<SavedTrip[]>('/api/v1/me/trips', {}, true),
  saveTrip: (trip: SavedTripIn) => request<SavedTrip>('/api/v1/me/trips', { method: 'POST', body: JSON.stringify(trip) }, true),
  deleteTrip: (id: number) => request<void>(`/api/v1/me/trips/${id}`, { method: 'DELETE' }, true),
}

// /accuracy returns free-form JSON (live + offline sections); typed here by hand.
export type CalibrationBin = { count: number; mean_predicted: number; observed?: number; observed_rate?: number }
export type AccuracyResponse = {
  live: {
    period: string
    matched_predictions: number
    brier?: Record<string, number | null>
    observed?: Record<string, number>
    calibration_connections?: CalibrationBin[]
    calibration_on_time?: CalibrationBin[]
  }
  offline: {
    model?: {
      version: string
      trained_at: string
      train_months: string[]
      test_months: string[]
      n_train: number
      n_test: number
      mean_pinball: Record<string, number>
      cancellation: Record<string, number>
      coverage: Record<string, number>
    }
    replay?: {
      model_version: string
      months: string[]
      journeys: number
      journeys_with_transfer: number
      brier: Record<string, Record<string, number>>
      calibration: { on_time: CalibrationBin[]; held: CalibrationBin[] }
      by_buffer: { buffer: string; journeys: number; observed_held: number; predicted_held: number }[]
    }
  }
}
