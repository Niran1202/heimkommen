import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { Journey } from '../api/client'

/** Straight-line sketch of the journey on OpenStreetMap tiles (light usage, with attribution). */
export function JourneyMap({ journey }: { journey: Journey }) {
  const element = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!element.current) return
    const map = L.map(element.current, { scrollWheelZoom: false, attributionControl: true })
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 18,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map)

    const points: L.LatLngExpression[] = []
    journey.legs.forEach((leg, index) => {
      const a = leg.origin
      const b = leg.destination
      if (a.lat == null || a.lon == null || b.lat == null || b.lon == null) return
      const style = leg.risk.modelled
        ? { color: '#2a78d6', weight: 4 }
        : { color: '#52514e', weight: 3, dashArray: '6 6' }
      L.polyline([[a.lat, a.lon], [b.lat, b.lon]], style).addTo(map).bindTooltip(`${leg.route} ${leg.departure}–${leg.arrival}`)
      if (index === 0) points.push([a.lat, a.lon])
      points.push([b.lat, b.lon])
    })
    points.forEach((p, i) => {
      L.circleMarker(p, { radius: 6, color: '#fcfcfb', weight: 2, fillColor: i === 0 || i === points.length - 1 ? '#0b0b0b' : '#eb6834', fillOpacity: 1 }).addTo(map)
    })
    if (points.length) map.fitBounds(L.latLngBounds(points), { padding: [24, 24] })
    return () => {
      map.remove()
    }
  }, [journey])

  return <div ref={element} className="journey-map" aria-label="Map of the journey" />
}
