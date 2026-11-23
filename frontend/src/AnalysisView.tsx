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
  { id: 'Difference', label: 'Build outer envelopes and compare banklines' },
  { id: 'Points', label: 'Rank expansion and contraction patches' },
]

export default function AnalysisView({ summary }: AnalysisViewProps): React.JSX.Element {
  const [endId, setEndId] = useState('')
  const [startId, setStartId] = useState('')
  const [mode, setMode] = useState<'dates' | 'periods'>('dates')
  const [sensor, setSensor] = useState<'optical' | 'microwave'>('optical')
  const [windowDays, setWindowDays] = useState(15)
  const [earlierStart, setEarlierStart] = useState('')
  const [earlierEnd, setEarlierEnd] = useState('')
  const [laterStart, setLaterStart] = useState('')
  const [laterEnd, setLaterEnd] = useState('')
  const [ackPartial, setAckPartial] = useState(false)
  const [preflightNote, setPreflightNote] = useState<string | null>(null)
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
  const [showStartBank, setShowStartBank] = useState(true)
  const [showEndBank, setShowEndBank] = useState(true)
  const [showEarlierEnvelope, setShowEarlierEnvelope] = useState(false)
  const [showLaterEnvelope, setShowLaterEnvelope] = useState(false)
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

  const requestParams = (): Record<string, string | number | boolean> => {
    if (mode === 'periods') {
      return {
        mode: 'periods',
        sensor,
        earlier_start: earlierStart,
        earlier_end: earlierEnd,
        later_start: laterStart,
        later_end: laterEnd,
        acknowledge_partial: ackPartial,
      }
    }
    return {
      mode: 'dates',
      sensor,
      window_days: windowDays,
      later: endId,
      earlier: startId,
      acknowledge_partial: ackPartial,
    }
  }

  const compute = (): void => {
    if (running) return
    if (mode === 'dates') {
      if (!endId) return
      if (startId !== '' && startId >= endId) {
        setError('Earlier date has to be before the later date')
        return
      }
    } else if (!earlierStart || !earlierEnd || !laterStart || !laterEnd) {
      setError('Period mode needs earlier and later start/end dates')
      return
    }
    const params = requestParams()
    setError(null)
    setPreflightNote(null)
    setHit(null)
    setRunning(true)
    setStep('Base optical')
    setDetail('Checking scene availability')
    void api.preflight(params).then((flight) => {
      if (!flight.ok) {
        setRunning(false)
        setError(flight.detail || 'No usable scenes for this request')
        return
      }
      setPreflightNote(
        `${flight.sensor}: earlier ${flight.earlier.scene_count} scenes (${flight.earlier.earliest_acquisition}→${flight.earlier.latest_acquisition}); `
        + `later ${flight.later.scene_count} scenes (${flight.later.earliest_acquisition}→${flight.later.latest_acquisition}).`,
      )
      setDetail('Starting downloads')
      return api.compute(params)
    }).catch((err: unknown) => {
      const message = err instanceof Error ? err.message : 'Compute did not start'
      if (message.toLowerCase().includes('already running')) {
        return
      }
      setRunning(false)
      setError(message)
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

  const place = hit?.pixel_label
  const acceptedPartial = !change?.requires_ack || ackPartial
  const erosionText = acceptedPartial ? (change?.erosion_display ?? '—') : '—'
  const depositionText = acceptedPartial ? (change?.deposition_display ?? '—') : '—'
  const netText = acceptedPartial ? (change?.net_water_change_display ?? '—') : '—'
  const activeStep = STEPS.findIndex((item) => item.id === step)
  const showChangeLayers = Boolean(acceptedPartial && change)

  return (
    <div className="work">
      <aside className="rail">
        <h2>Compare</h2>
        <div className="dates">
          <label className="field">
            Mode
            <select value={mode} onChange={(event) => setMode(event.target.value as 'dates' | 'periods')}>
              <option value="dates">Two dates (Mode A)</option>
              <option value="periods">Two periods (Mode B)</option>
            </select>
          </label>
          <label className="field">
            Sensor
            <select value={sensor} onChange={(event) => setSensor(event.target.value as 'optical' | 'microwave')}>
              <option value="optical">Sentinel-2 optical (≥2017-03-28)</option>
              <option value="microwave">Sentinel-1 microwave (≥2014-10-03)</option>
            </select>
          </label>
          {mode === 'dates' ? (
            <>
              <label className="field">
                Window
                <select value={windowDays} onChange={(event) => setWindowDays(Number(event.target.value))}>
                  <option value={1}>1 day</option>
                  <option value={15}>15 days</option>
                  <option value={30}>30 days</option>
                  <option value={60}>60 days</option>
                </select>
              </label>
              <label className="field">
                Earlier date
                <input type="date" value={startId} max={endId || undefined} onChange={(event) => setStartId(event.target.value)} />
              </label>
              <label className="field">
                Later date
                <input type="date" value={endId} onChange={(event) => setEndId(event.target.value)} />
              </label>
            </>
          ) : (
            <>
              <label className="field">Earlier start<input type="date" value={earlierStart} onChange={(event) => setEarlierStart(event.target.value)} /></label>
              <label className="field">Earlier end<input type="date" value={earlierEnd} onChange={(event) => setEarlierEnd(event.target.value)} /></label>
              <label className="field">Later start<input type="date" value={laterStart} onChange={(event) => setLaterStart(event.target.value)} /></label>
              <label className="field">Later end<input type="date" value={laterEnd} onChange={(event) => setLaterEnd(event.target.value)} /></label>
            </>
          )}
        </div>
        <p className="note">
          {mode === 'dates'
            ? `Mode A: each date ends a ${windowDays}-day composite. This is not the full interval between the two dates.`
            : 'Mode B: each period is composited independently. The gap between periods is not filled.'}
        </p>
        <label className="check">
          <input type="checkbox" checked={ackPartial} onChange={() => setAckPartial((value) => !value)} />
          Acknowledge partial corridor coverage (&lt;70% valid)
        </label>
        <button type="button" className="compute" disabled={running || (mode === 'dates' ? !endId : false)} onClick={compute}>
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
          <div className="figure"><b className="tone-erosion">{erosionText}</b><span>Expansion</span></div>
          <div className="figure"><b className="tone-deposition">{depositionText}</b><span>Contraction</span></div>
          <div className="figure"><b>{netText}</b><span>Net change</span></div>
          <div className="figure"><b>{change?.valid_fraction != null ? `${(100 * change.valid_fraction).toFixed(0)}%` : '—'}</b><span>Valid overlap</span></div>
        </div>
        {error && <p className="note">{error}</p>}
        {preflightNote && <p className="note">{preflightNote}</p>}
        {!change && !running && <p className="note">Earlier and later outer banklines are compared on common valid observations only.</p>}
        {change?.earlier_label && change.later_label && (
          <p className="note">Earlier {change.earlier_label} · Later {change.later_label}. Net corridor change {netText}.</p>
        )}
        {change?.acquisition && (
          <p className="note">
            Scenes: earlier {change.acquisition.earlier?.scene_count ?? '—'} ({change.acquisition.earlier?.latest_scene ?? '—'}) ·
            later {change.acquisition.later?.scene_count ?? '—'} ({change.acquisition.later?.latest_scene ?? '—'})
          </p>
        )}
        {change?.partial_coverage && (
          <p className="note">
            Partial coverage warning: valid overlap {(100 * (change.valid_fraction ?? 0)).toFixed(1)}%
            {' '}(threshold {100 * (change.min_valid_fraction ?? 0.7)}%).
            {' '}{change.coverage_warning || 'Do not claim full Brahmaputra coverage.'}
            {!ackPartial ? ' Tick the acknowledge box above if you accept a partial-corridor result.' : ' Acknowledged.'}
          </p>
        )}
        {change?.transect_qc && (
          <p className="note">
            Transects both_ok {change.transect_qc.both_ok}/{change.transect_qc.total_transects}
            {' '}({change.transect_qc.pct_of_mutual_span}% inside mutual span
            {' '}{change.transect_qc.first_both_ok_chainage_m}–{change.transect_qc.last_both_ok_chainage_m} m).
            {' '}Not full-guide accuracy.
          </p>
        )}
        {change?.note && <p className="note">{change.note}</p>}
        {change?.disclaimer && <p className="note">{change.disclaimer}</p>}
        <div className="checks">
          <label className="check"><input type="checkbox" checked={showRiver} onChange={() => setShowRiver((value) => !value)} /> Optical water</label>
          <label className="check"><input type="checkbox" checked={showMicrowave} onChange={() => setShowMicrowave((value) => !value)} /> Microwave water</label>
          <label className="check"><input type="checkbox" checked={showErosion} onChange={() => setShowErosion((value) => !value)} /> Expansion</label>
          <label className="check"><input type="checkbox" checked={showDeposition} onChange={() => setShowDeposition((value) => !value)} /> Contraction</label>
          <label className="check"><input type="checkbox" checked={showStartBank} onChange={() => setShowStartBank((value) => !value)} /> Earlier banks</label>
          <label className="check"><input type="checkbox" checked={showEndBank} onChange={() => setShowEndBank((value) => !value)} /> Later banks</label>
          <label className="check"><input type="checkbox" checked={showEarlierEnvelope} onChange={() => setShowEarlierEnvelope((value) => !value)} /> Earlier envelope</label>
          <label className="check"><input type="checkbox" checked={showLaterEnvelope} onChange={() => setShowLaterEnvelope((value) => !value)} /> Later envelope</label>
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
            <PointTable title="Expansion patches" tone="erosion" rows={points.erosion} total={points.erosion_count} selectedLat={pick?.lat ?? null} onSelect={(lat, lon) => inspect(lat, lon, true)} />
            <PointTable title="Contraction patches" tone="deposition" rows={points.deposition} total={points.deposition_count} selectedLat={pick?.lat ?? null} onSelect={(lat, lon) => inspect(lat, lon, true)} />
          </>
        )}
      </aside>
      <div className="stage">
        <MapCanvas
          banks={change?.banks ?? null}
          endpoints={summary.study_area.endpoints}
          footprint={ROI}
          bounds={change?.bounds ?? ROI}
          laterUrl={change?.river_png ?? null}
          microwaveUrl={change?.microwave_png ?? null}
          showMicrowave={showMicrowave}
          erosionUrl={change?.erosion_png ?? null}
          depositionUrl={change?.deposition_png ?? null}
          earlierEnvelopeUrl={change?.earlier_envelope_png ?? null}
          laterEnvelopeUrl={change?.later_envelope_png ?? null}
          showLater={showRiver}
          showErosion={showErosion && showChangeLayers}
          showDeposition={showDeposition && showChangeLayers}
          showStartBank={showStartBank}
          showEndBank={showEndBank}
          showEarlierEnvelope={showEarlierEnvelope}
          showLaterEnvelope={showLaterEnvelope}
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

function bankLines(banks: GeoJSON.FeatureCollection, prefix: string): GeoJSON.FeatureCollection {
  const features = banks.features.filter((feature) => String(feature.properties?.role ?? '').startsWith(prefix))
  return { type: 'FeatureCollection', features }
}

function MapCanvas(props: {
  banks: GeoJSON.FeatureCollection | null | undefined
  endpoints: Endpoints
  footprint: Bounds | null
  bounds: Bounds | null
  laterUrl: string | null
  microwaveUrl: string | null
  erosionUrl: string | null
  depositionUrl: string | null
  earlierEnvelopeUrl: string | null
  laterEnvelopeUrl: string | null
  showLater: boolean
  showMicrowave: boolean
  showErosion: boolean
  showDeposition: boolean
  showStartBank: boolean
  showEndBank: boolean
  showEarlierEnvelope: boolean
  showLaterEnvelope: boolean
  satellite: boolean
  pick: { lat: number; lon: number } | null
  focus: { lat: number; lon: number; token: number } | null
  busy: boolean
  revision: string
  onPick: (lat: number, lon: number) => void
}): React.JSX.Element {
  const { upstream, downstream } = props.endpoints
  const frame = props.bounds
  const bankEndpoints = (props.banks?.features ?? []).filter((feature) =>
    String(feature.properties?.role ?? '').includes('endpoint'),
  )
  return (
    <main className="map-shell" aria-label="Brahmaputra bankline comparison map">
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
        {props.showEarlierEnvelope && props.earlierEnvelopeUrl && frame && (
          <ImageOverlay key={`env-e-${props.revision}`} url={props.earlierEnvelopeUrl} bounds={frameOf(frame)} opacity={0.45} interactive={false} />
        )}
        {props.showLaterEnvelope && props.laterEnvelopeUrl && frame && (
          <ImageOverlay key={`env-l-${props.revision}`} url={props.laterEnvelopeUrl} bounds={frameOf(frame)} opacity={0.45} interactive={false} />
        )}
        {props.showMicrowave && props.microwaveUrl && frame && (
          <ImageOverlay key={`sar-${props.revision}`} url={props.microwaveUrl} bounds={frameOf(frame)} opacity={0.35} interactive={false} />
        )}
        {props.showLater && props.laterUrl && frame && (
          <ImageOverlay key={`late-${props.revision}`} url={props.laterUrl} bounds={frameOf(frame)} opacity={0.4} interactive={false} />
        )}
        {props.showDeposition && props.depositionUrl && frame && (
          <ImageOverlay key={`dep-${props.revision}`} url={props.depositionUrl} bounds={frameOf(frame)} opacity={0.9} interactive={false} />
        )}
        {props.showErosion && props.erosionUrl && frame && (
          <ImageOverlay key={`ero-${props.revision}`} url={props.erosionUrl} bounds={frameOf(frame)} opacity={0.9} interactive={false} />
        )}
        {props.showStartBank && props.banks && (
          <GeoJSON
            key={`banks-start-${props.revision}`}
            data={bankLines(props.banks, 'start')}
            style={{ color: '#38bdf8', weight: 2.2, opacity: 0.95 }}
          />
        )}
        {props.showEndBank && props.banks && (
          <GeoJSON
            key={`banks-end-${props.revision}`}
            data={bankLines(props.banks, 'end')}
            style={{ color: '#f59e0b', weight: 2.2, opacity: 1 }}
          />
        )}
        {bankEndpoints.map((feature, index) => {
          const coords = feature.geometry.type === 'Point' ? feature.geometry.coordinates : null
          if (!coords) return null
          const role = String(feature.properties?.role ?? '')
          const later = role.startsWith('later_')
          return (
            <CircleMarker
              key={`ep-${props.revision}-${index}`}
              center={[coords[1], coords[0]]}
              radius={4}
              pathOptions={{ color: '#fff', weight: 1.5, fillColor: later ? '#f59e0b' : '#38bdf8', fillOpacity: 1 }}
            >
              <Tooltip direction="top">{role.replace('endpoint_', '').replace('later_', 'later ')}</Tooltip>
            </CircleMarker>
          )
        })}
        <CircleMarker center={[upstream.lat, upstream.lon]} radius={5} pathOptions={{ color: '#fff', weight: 2, fillColor: '#38bdf8', fillOpacity: 1 }}>
          <Tooltip direction="left">{upstream.name} (upstream)</Tooltip>
        </CircleMarker>
        <CircleMarker center={[downstream.lat, downstream.lon]} radius={5} pathOptions={{ color: '#fff', weight: 2, fillColor: '#2563eb', fillOpacity: 1 }}>
          <Tooltip direction="right">{downstream.name} (downstream)</Tooltip>
        </CircleMarker>
        {props.pick && (
          <CircleMarker center={[props.pick.lat, props.pick.lon]} radius={7} pathOptions={{ color: '#1d4ed8', weight: 2, fillColor: '#f8fafc', fillOpacity: 1 }} />
        )}
        <ZoomControl position="bottomright" />
        <ScaleControl position="bottomleft" imperial={false} />
      </MapContainer>
      <div className="map-legend">
        {props.showStartBank && <span><i className="swatch" style={{ background: '#38bdf8' }} /> Earlier banks</span>}
        {props.showEndBank && <span><i className="swatch" style={{ background: '#f59e0b' }} /> Later banks</span>}
        <span><i className="swatch water" /> Optical</span>
        <span><i className="swatch microwave" /> Microwave</span>
        <span><i className="swatch erosion" /> Expansion</span>
        <span><i className="swatch deposition" /> Contraction</span>
        <span><i className="swatch box" /> Study extent</span>
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
