import { Loader2 } from 'lucide-react'
import {
  CircleMarker,
  GeoJSON,
  ImageOverlay,
  MapContainer,
  ScaleControl,
  TileLayer,
  Tooltip,
  ZoomControl,
  useMap,
  useMapEvents,
} from 'react-leaflet'
import L from 'leaflet'
import type { LatLngBoundsExpression } from 'leaflet'
import { useEffect, useRef, useState } from 'react'
import 'leaflet/dist/leaflet.css'

import { api } from './api'
import type { ComputeStatus } from './api'
import type { Bounds, ChangePoint, ChangePoints, ChangeStats, Endpoints, IdentifyResult, PortalSummary } from './types'

interface AnalysisViewProps {
  summary: PortalSummary
}

interface PointTableProps {
  title: string
  tone: 'erosion' | 'deposition'
  rows: ChangePoint[]
  total: number
  selectedLat: number | null
  onSelect: (latitude: number, longitude: number) => void
}

function PointTable({ title, tone, rows, total, selectedLat, onSelect }: PointTableProps): React.JSX.Element {
  return (
    <section className="point-block">
      <h3 className={tone === 'erosion' ? 'tone-erosion' : 'tone-deposition'}>{title}</h3>
      <p className="note">{rows.length === 0 ? 'No patch in this pair.' : `Largest ${rows.length} of ${total}`}</p>
      {rows.length > 0 && (
        <div className="point-scroll">
          <table className="point-table">
            <thead>
              <tr><th>km²</th><th>Latitude</th><th>Longitude</th></tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${tone}-${row.rank}`} className={selectedLat != null && Math.abs(selectedLat - row.latitude) < 0.0002 ? 'active' : ''}>
                  <td className={tone === 'erosion' ? 'tone-erosion' : 'tone-deposition'}>{row.area_km2}</td>
                  <td><button type="button" className="linkish" onClick={() => onSelect(row.latitude, row.longitude)}>{row.latitude.toFixed(5)}</button></td>
                  <td>{row.longitude.toFixed(5)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

const ROI: Bounds = { west: 89.5, south: 25.5, east: 96, north: 28.5 }

const STEPS: { id: string; label: string }[] = [
  { id: 'Base optical', label: 'Fetch the start-date optical mask' },
  { id: 'Base microwave', label: 'Fetch the start-date microwave mask' },
  { id: 'Current optical', label: 'Fetch the end-date optical mask' },
  { id: 'Current microwave', label: 'Fetch the end-date microwave mask' },
  { id: 'Difference', label: 'Draw the centreline and compare the two dates' },
  { id: 'Points', label: 'Rank erosion and deposition points' },
]

export default function AnalysisView({ summary }: AnalysisViewProps): React.JSX.Element {
  const [endId, setEndId] = useState('')
  const [startId, setStartId] = useState('')
  const [change, setChange] = useState<ChangeStats | null>(null)
  const [points, setPoints] = useState<ChangePoints | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const [step, setStep] = useState('')
  const [detail, setDetail] = useState('')
  const [satellite, setSatellite] = useState(true)
  const [showRiver, setShowRiver] = useState(true)
  const [showMicrowave, setShowMicrowave] = useState(true)
  const [showErosion, setShowErosion] = useState(true)
  const [showDeposition, setShowDeposition] = useState(true)
  const [pick, setPick] = useState<{ lat: number; lon: number } | null>(null)
  const [focus, setFocus] = useState<{ lat: number; lon: number; token: number } | null>(null)
  const [hit, setHit] = useState<IdentifyResult | null>(null)
  const locateToken = useRef(0)

  useEffect(() => {
    void api.latest().then((row) => {
      if (row.end) setEndId(row.end)
      else setError('No recent Sentinel scene was found')
    }).catch((err: unknown) => {
      setError(err instanceof Error ? err.message : 'Earth Engine did not respond')
    })
  }, [])

  useEffect(() => {
    if (!running) return
    let stop = false
    const read = (): void => {
      void api.computeStatus().then((status: ComputeStatus) => {
        if (stop) return
        setStep(status.step)
        setDetail(status.detail)
        if (!status.done) return
        setRunning(false)
        if (status.error) {
          setError(status.error)
          return
        }
        if (status.change) setChange(status.change)
        if (status.points) setPoints(status.points)
        setError(null)
      }).catch((err: unknown) => {
        if (!stop) setError(err instanceof Error ? err.message : 'The progress update failed')
      })
    }
    read()
    const timer = window.setInterval(read, 1000)
    return () => {
      stop = true
      window.clearInterval(timer)
    }
  }, [running])

  const compute = (): void => {
    if (!endId || running) return
    if (startId !== '' && startId >= endId) {
      setError('Start date has to be before the end date')
      return
    }
    setError(null)
    setHit(null)
    setRunning(true)
    setStep('Base optical')
    setDetail('Starting')
    void api.compute(endId, startId).catch((err: unknown) => {
      setRunning(false)
      setError(err instanceof Error ? err.message : 'Compute did not start')
    })
  }

  const inspect = (lat: number, lon: number, fly = false): void => {
    setPick({ lat, lon })
    if (fly) setFocus({ lat, lon, token: Date.now() })
    setHit(null)
    if (!change) return
    const token = locateToken.current + 1
    locateToken.current = token
    void api.identify(lon, lat, change.later_id ?? '', change.earlier_id ?? '').then((result) => {
      if (locateToken.current === token) setHit(result)
    }).catch((err: unknown) => {
      if (locateToken.current === token) setError(err instanceof Error ? err.message : 'Location lookup failed')
    })
  }

  const place = hit?.pixel_label.replace('Corridor expansion', 'Erosion').replace('Corridor contraction', 'Deposition')
  const erosionText = change?.erosion_display ?? '—'
  const depositionText = change?.deposition_display ?? '—'
  const netText = change?.net_water_change_display ?? '—'
  const activeStep = STEPS.findIndex((item) => item.id === step)

  return (
    <div className="work">
      <aside className="rail">
        <h2>Compare</h2>
        <div className="dates">
          <label className="field">
            Start
            <input type="date" value={startId} max={endId} onChange={(event) => setStartId(event.target.value)} />
          </label>
          <label className="field">
            End
            <input type="date" value={endId} onChange={(event) => setEndId(event.target.value)} />
          </label>
        </div>
        <button type="button" className="compute" disabled={running || !endId} onClick={compute}>
          {running && <Loader2 className="spin" size={16} />}
          Compute
        </button>
        {running && (
          <ol className="steps">
            {STEPS.map((item, index) => (
              <li key={item.id} className={index < activeStep || step === 'Done' ? 'done' : index === activeStep ? 'active' : ''}>
                <i />
                <span>{item.label}{index === activeStep && detail ? ` — ${detail}` : ''}</span>
              </li>
            ))}
          </ol>
        )}
        <div className="figures">
          <div className="figure"><b className="tone-erosion">{erosionText}</b><span>Erosion</span></div>
          <div className="figure"><b className="tone-deposition">{depositionText}</b><span>Deposition</span></div>
          <div className="figure"><b>{change?.later_water_display ?? '—'}</b><span>Optical water</span></div>
          <div className="figure"><b>{change?.microwave_water_display ?? '—'}</b><span>Microwave water</span></div>
        </div>
        {error && <p className="note">{error}</p>}
        {!change && !running && <p className="note">Start is the base. End is the current state. Compute compares those two.</p>}
        {change?.earlier_label && change.later_label && (
          <p className="note">{change.earlier_label} is the base. {change.later_label} is current. Net optical water {netText}.</p>
        )}
        {change && (
          <p className="note">Optical scene {change.optical_scene ?? '—'} · Microwave scene {change.microwave_scene ?? '—'}</p>
        )}
        <div className="checks">
          <label className="check"><input type="checkbox" checked={showRiver} onChange={() => setShowRiver((value) => !value)} /> Optical</label>
          <label className="check"><input type="checkbox" checked={showMicrowave} onChange={() => setShowMicrowave((value) => !value)} /> Microwave</label>
          <label className="check"><input type="checkbox" checked={showErosion} onChange={() => setShowErosion((value) => !value)} /> Erosion</label>
          <label className="check"><input type="checkbox" checked={showDeposition} onChange={() => setShowDeposition((value) => !value)} /> Deposition</label>
          <label className="check"><input type="checkbox" checked={satellite} onChange={() => setSatellite((value) => !value)} /> Satellite</label>
        </div>
        <div className="readout">
          {pick && <strong>{pick.lat.toFixed(5)}, {pick.lon.toFixed(5)}</strong>}
          {!change && <p className="note">Compute a pair, then click the map for that point.</p>}
          {change && !hit && <p className="note">Click the map. The class is for the computed base and current dates.</p>}
          {hit && (
            <>
              <strong>{hit.latitude.toFixed(5)}, {hit.longitude.toFixed(5)}</strong>
              <p>{place}</p>
              {hit.zone && <p>{hit.zone.change_class === 'corridor_expansion' ? 'Erosion' : 'Deposition'} patch {hit.zone.area_display}</p>}
              {hit.section && <p>{hit.section.section_id} · {hit.section.chainage_display} · {hit.section.width_earlier_m ?? '—'} m → {hit.section.width_later_m ?? '—'} m</p>}
            </>
          )}
        </div>
        {points && (
          <>
            <PointTable title="Erosion" tone="erosion" rows={points.erosion} total={points.erosion_count} selectedLat={pick?.lat ?? null} onSelect={(lat, lon) => inspect(lat, lon, true)} />
            <PointTable title="Deposition" tone="deposition" rows={points.deposition} total={points.deposition_count} selectedLat={pick?.lat ?? null} onSelect={(lat, lon) => inspect(lat, lon, true)} />
          </>
        )}
      </aside>
      <div className="stage">
        <MapCanvas
          centerline={change?.centerline ?? null}
          endpoints={summary.study_area.endpoints}
          footprint={ROI}
          bounds={change?.bounds ?? ROI}
          laterUrl={change?.river_png ?? null}
          microwaveUrl={change?.microwave_png ?? null}
          showMicrowave={showMicrowave}
          erosionUrl={change?.erosion_png ?? null}
          depositionUrl={change?.deposition_png ?? null}
          showLater={showRiver}
          showErosion={showErosion}
          showDeposition={showDeposition}
          satellite={satellite}
          pick={pick}
          focus={focus}
          busy={false}
          onPick={inspect}
          revision={`${endId}-${startId}`}
        />
      </div>
    </div>
  )
}

function frameOf(bounds: Bounds): LatLngBoundsExpression {
  return [[bounds.south, bounds.west], [bounds.north, bounds.east]]
}

function footprintFeature(bounds: Bounds): GeoJSON.Feature {
  const { west, south, east, north } = bounds
  return {
    type: 'Feature',
    properties: {},
    geometry: {
      type: 'Polygon',
      coordinates: [[[west, south], [east, south], [east, north], [west, north], [west, south]]],
    },
  }
}

function MapClick({ onPick }: { onPick: (lat: number, lon: number) => void }): null {
  useMapEvents({
    click(event) {
      onPick(event.latlng.lat, event.latlng.lng)
    },
  })
  return null
}

function FlyTo({ focus }: { focus: { lat: number; lon: number; token: number } | null }): null {
  const map = useMap()
  useEffect(() => {
    if (!focus) return
    map.flyTo([focus.lat, focus.lon], Math.max(map.getZoom(), 11))
  }, [focus, map])
  return null
}

function FitMask({ bounds, revision }: { bounds: Bounds | null; revision: string }): null {
  const map = useMap()
  useEffect(() => {
    if (!bounds) return
    const box = L.latLngBounds([bounds.south, bounds.west], [bounds.north, bounds.east])
    const fit = (): void => {
      map.invalidateSize()
      if (box.isValid()) map.fitBounds(box, { padding: [28, 28] })
    }
    fit()
    const node = map.getContainer()
    let seen = node.clientWidth
    const observer = new ResizeObserver(() => {
      const width = node.clientWidth
      if (width > 0 && seen === 0) {
        seen = width
        fit()
      }
    })
    observer.observe(node)
    return () => observer.disconnect()
  }, [bounds, map, revision])
  return null
}

function MapCanvas(props: {
  centerline: GeoJSON.Feature | null | undefined
  endpoints: Endpoints
  footprint: Bounds | null
  bounds: Bounds | null
  laterUrl: string | null
  microwaveUrl: string | null
  erosionUrl: string | null
  depositionUrl: string | null
  showLater: boolean
  showMicrowave: boolean
  showErosion: boolean
  showDeposition: boolean
  satellite: boolean
  pick: { lat: number; lon: number } | null
  focus: { lat: number; lon: number; token: number } | null
  busy: boolean
  revision: string
  onPick: (lat: number, lon: number) => void
}): React.JSX.Element {
  const { upstream, downstream } = props.endpoints
  const frame = props.bounds
  const axis = props.centerline?.geometry ? props.centerline : null
  return (
    <main className="map-shell" aria-label="Brahmaputra water-mask map">
      <MapContainer center={[26.2, 91.4]} zoom={8} minZoom={6} maxZoom={18} zoomControl={false}>
        <FitMask bounds={frame} revision={props.revision} />
        <FlyTo focus={props.focus} />
        <MapClick onPick={props.onPick} />
        {props.satellite ? (
          <TileLayer
            url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
            attribution="Tiles &copy; Esri"
            maxNativeZoom={17}
          />
        ) : (
          <TileLayer
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution="&copy; OpenStreetMap"
          />
        )}
        {props.footprint && (
          <GeoJSON
            key={`fp-${props.revision}`}
            data={footprintFeature(props.footprint)}
            style={{ color: '#d97706', weight: 1.2, dashArray: '5 4', fillOpacity: 0 }}
          />
        )}
        {props.showMicrowave && props.microwaveUrl && frame && (
          <ImageOverlay key={`sar-${props.revision}`} url={props.microwaveUrl} bounds={frameOf(frame)} opacity={0.35} interactive={false} />
        )}
        {props.showLater && props.laterUrl && frame && (
          <ImageOverlay key={`late-${props.revision}`} url={props.laterUrl} bounds={frameOf(frame)} opacity={0.4} interactive={false} />
        )}
        {props.showDeposition && props.depositionUrl && frame && (
          <ImageOverlay key={`dep-${props.revision}`} url={props.depositionUrl} bounds={frameOf(frame)} opacity={0.55} interactive={false} />
        )}
        {props.showErosion && props.erosionUrl && frame && (
          <ImageOverlay key={`ero-${props.revision}`} url={props.erosionUrl} bounds={frameOf(frame)} opacity={0.45} interactive={false} />
        )}
        {axis && (
          <GeoJSON key={`axis-case-${props.revision}`} data={axis} style={{ color: '#0f172a', weight: 2.5, opacity: 0.8 }} />
        )}
        {axis && (
          <GeoJSON key={`axis-${props.revision}`} data={axis} style={{ color: '#ffffff', weight: 1, opacity: 1 }} />
        )}
        <CircleMarker center={[upstream.lat, upstream.lon]} radius={5} pathOptions={{ color: '#fff', weight: 2, fillColor: '#38bdf8', fillOpacity: 1 }}>
          <Tooltip direction="left">{upstream.name}</Tooltip>
        </CircleMarker>
        <CircleMarker center={[downstream.lat, downstream.lon]} radius={5} pathOptions={{ color: '#fff', weight: 2, fillColor: '#2563eb', fillOpacity: 1 }}>
          <Tooltip direction="right">{downstream.name}</Tooltip>
        </CircleMarker>
        {props.pick && (
          <CircleMarker center={[props.pick.lat, props.pick.lon]} radius={7} pathOptions={{ color: '#1d4ed8', weight: 2, fillColor: '#f8fafc', fillOpacity: 1 }} />
        )}
        <ZoomControl position="bottomright" />
        <ScaleControl position="bottomleft" imperial={false} />
      </MapContainer>
      <div className="map-legend">
        <span><i className="swatch centre" /> Centre</span>
        <span><i className="swatch water" /> Optical</span>
        <span><i className="swatch microwave" /> Microwave</span>
        <span><i className="swatch erosion" /> Erosion</span>
        <span><i className="swatch deposition" /> Deposition</span>
        <span><i className="swatch box" /> Mask extent</span>
      </div>
      {props.busy && (
        <div className="map-busy">
          <Loader2 className="spin" size={28} />
          <p>Reading this location</p>
        </div>
      )}
    </main>
  )
}
