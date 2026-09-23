import { useEffect, useId, useRef, useState } from 'react'
import { api, type Station } from '../api/client'

type Props = {
  label: string
  value: string
  onChange: (value: string) => void
  onLocate?: () => void
  locating?: boolean
  placeholder?: string
}

/** Station autocomplete backed by /api/v1/stations. The raw text is also accepted by the API. */
export function StationInput({ label, value, onChange, onLocate, locating, placeholder }: Props) {
  const id = useId()
  const [suggestions, setSuggestions] = useState<Station[]>([])
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const skipNext = useRef(false)

  useEffect(() => {
    // Picking a suggestion changes the value; don't search again for it.
    if (skipNext.current) {
      skipNext.current = false
      return
    }
    if (value.trim().length < 2) {
      setSuggestions([])
      return
    }
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      api.searchStations(value, controller.signal)
        .then((r) => {
          setSuggestions(r.stations)
          setOpen(true)
          setActive(-1)
        })
        .catch(() => setSuggestions([]))
    }, 180)
    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [value])

  const choose = (station: Station) => {
    skipNext.current = true
    onChange(station.name)
    setOpen(false)
  }

  return (
    <div className="field station-field">
      <label htmlFor={id}>{label}</label>
      <div className="input-row">
        <input
          id={id}
          value={value}
          placeholder={placeholder}
          autoComplete="off"
          role="combobox"
          aria-expanded={open && suggestions.length > 0}
          aria-controls={`${id}-list`}
          onChange={(e) => onChange(e.target.value)}
          onFocus={() => suggestions.length && setOpen(true)}
          onBlur={() => window.setTimeout(() => setOpen(false), 120)}
          onKeyDown={(e) => {
            if (!open || !suggestions.length) return
            if (e.key === 'ArrowDown') {
              e.preventDefault()
              setActive((a) => Math.min(a + 1, suggestions.length - 1))
            } else if (e.key === 'ArrowUp') {
              e.preventDefault()
              setActive((a) => Math.max(a - 1, 0))
            } else if (e.key === 'Enter' && active >= 0) {
              e.preventDefault()
              choose(suggestions[active])
            } else if (e.key === 'Escape') {
              setOpen(false)
            }
          }}
        />
        {onLocate && (
          <button type="button" className="icon-button" onClick={onLocate} disabled={locating}
            aria-label="Use nearest station to my location" title="Nearest station">
            {locating ? '…' : '◎'}
          </button>
        )}
      </div>
      {open && suggestions.length > 0 && (
        <ul className="suggestions" id={`${id}-list`} role="listbox">
          {suggestions.map((s, i) => (
            <li key={s.id} role="option" aria-selected={i === active}
              className={i === active ? 'active' : undefined}
              onMouseDown={(e) => {
                e.preventDefault()
                choose(s)
              }}>
              <span>{s.name}</span>
              {s.is_rail && <span className="tag">Train</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
