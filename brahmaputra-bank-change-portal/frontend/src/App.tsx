import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  GitCompare,
  Layers3,
  Loader2,
  MapPinned,
  Radar,
  Waves,
} from 'lucide-react'
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { api } from './api'
import type { Comparison, EpochSummary, ReachStat, StudyArea } from './types'

const MapWorkspace = lazy(() => import('./MapWorkspace'))

function statusLabel(status: string): string {
  return status.replaceAll('_', ' ')
}

export default function App(): React.JSX.Element {
  const [study, setStudy] = useState<StudyArea | null>(null)
  const [epochs, setEpochs] = useState<EpochSummary[]>([])
  const [dateA, setDateA] = useState('')
  const [dateB, setDateB] = useState('')
  const [layersA, setLayersA] = useState<Record<string, GeoJSON.GeoJsonObject>>()
  const [layersB, setLayersB] = useState<Record<string, GeoJSON.GeoJsonObject>>()
  const [centerline, setCenterline] = useState<GeoJSON.GeoJsonObject>()
  const [comparison, setComparison] = useState<Comparison | null>(null)
  const [section, setSection] = useState<Record<string, unknown> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [toggles, setToggles] = useState({
    envelopeA: true,
    envelopeB: true,
    banksA: true,
    banksB: true,
    centerline: true,
    sections: true,
    change: true,
  })
  const [sensor, setSensor] = useState('all')
  const [month, setMonth] = useState('all')

  useEffect(() => {
    void (async () => {
      try {
        const [area, list, reference] = await Promise.all([
          api.studyArea(),
          api.epochs(),
          api.reference(),
        ])
        setStudy(area)
        setEpochs(list)
        setCenterline(reference.centerline)
        const processed = list.filter((item) => item.status === 'processed')
        if (processed.length >= 2) {
          setDateA(processed[0].date)
          setDateB(processed[processed.length - 1].date)
        } else if (processed[0]) {
          setDateA(processed[0].date)
          setDateB(processed[0].date)
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load API')
      } finally {
        setLoading(false)
      }
    })()
  }, [])

  const processed = useMemo(
    () => epochs.filter((item) => item.status === 'processed'),
    [epochs],
  )

  const visibleEpochs = useMemo(() => {
    return epochs.filter((item) => {
      if (sensor !== 'all' && !item.sensors.includes(sensor)) return false
      if (month !== 'all' && !item.date.startsWith(month)) return false
      return true
    })
  }, [epochs, month, sensor])

  useEffect(() => {
    void (async () => {
      const a = processed.find((item) => item.date === dateA)
      const b = processed.find((item) => item.date === dateB)
      if (!a || !b) return
      setLoading(true)
      try {
        const [la, lb, cmp] = await Promise.all([
          api.epochLayers(a.id),
          api.epochLayers(b.id),
          api.createComparison(a.id, b.id),
        ])
        setLayersA(la)
        setLayersB(lb)
        setComparison(cmp)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Compare failed')
      } finally {
        setLoading(false)
      }
    })()
  }, [dateA, dateB, processed])

  const latestVsPrevious = (): void => {
    if (processed.length < 2) return
    const sorted = [...processed].sort((a, b) => a.date.localeCompare(b.date))
    setDateA(sorted[sorted.length - 2].date)
    setDateB(sorted[sorted.length - 1].date)
  }

  const chartData =
    comparison?.reach_statistics?.map((row: ReachStat) => ({
      reach: row.reach_id,
      widthA: row.mean_width_a_m,
      widthB: row.mean_width_b_m,
    })) ?? []

  if (error) {
    return (
      <div className="fatal">
        <AlertTriangle />
        <p>The portal could not reach the API. Start FastAPI on port 8000.</p>
        <small>{error}</small>
      </div>
    )
  }

  return (
    <div className="shell">
      <header className="header">
        <div className="brand">
          <Waves size={20} />
          <div>
            <h1>Brahmaputra Bank Change Portal</h1>
            <span>Assam main stem · Sadiya to Dhubri · unvalidated prototype</span>
          </div>
        </div>
        <div className="header-meta">
          <span className="badge">CANDIDATE CHANGE</span>
          <span>{study ? `${(study.corridor_length_m / 1000).toFixed(0)} km corridor` : '…'}</span>
          {loading && <Loader2 className="spin" size={16} />}
        </div>
      </header>

      <div className="workspace">
        <aside className="panel left">
          <p className="eyebrow">Observations</p>
          <div className="row">
            <label>
              Sensor
              <select value={sensor} onChange={(event) => setSensor(event.target.value)}>
                <option value="all">All</option>
                <option value="sentinel-1">Sentinel-1 SAR</option>
                <option value="sentinel-2">Sentinel-2 optical</option>
                <option value="landsat">Landsat</option>
              </select>
            </label>
            <label>
              Month
              <select value={month} onChange={(event) => setMonth(event.target.value)}>
                <option value="all">All</option>
                {[...new Set(epochs.map((item) => item.date.slice(0, 7)))].map((value) => (
                  <option key={value} value={value}>{value}</option>
                ))}
              </select>
            </label>
          </div>
          <button type="button" className="primary" onClick={latestVsPrevious}>
            <GitCompare size={15} /> Latest vs Previous
          </button>
          <label>
            Date A
            <select value={dateA} onChange={(event) => setDateA(event.target.value)}>
              {visibleEpochs.map((item) => (
                <option key={item.id} value={item.date}>{item.date} · {item.sensors.join(',')}</option>
              ))}
            </select>
          </label>
          <label>
            Date B
            <select value={dateB} onChange={(event) => setDateB(event.target.value)}>
              {visibleEpochs.map((item) => (
                <option key={item.id} value={item.date}>{item.date} · {item.sensors.join(',')}</option>
              ))}
            </select>
          </label>
          <p className="eyebrow">Layers</p>
          {(
            [
              ['envelopeA', 'Envelope A'],
              ['envelopeB', 'Envelope B'],
              ['banksA', 'Proxy banks A'],
              ['banksB', 'Proxy banks B'],
              ['centerline', 'Reference centerline'],
              ['sections', '300 m sections'],
              ['change', 'Candidate change'],
            ] as const
          ).map(([key, label]) => (
            <label key={key} className="check">
              <input
                type="checkbox"
                checked={toggles[key]}
                onChange={() => setToggles((current) => ({ ...current, [key]: !current[key] }))}
              />
              {label}
            </label>
          ))}
          <p className="note">
            <Layers3 size={13} /> Outer boundaries are satellite proxy banklines, not confirmed geomorphic banks.
          </p>
          <p className="eyebrow">Acquisition status</p>
          <ul className="status-list">
            {epochs.map((item) => (
              <li key={item.id}>
                <i className={item.status} />
                {item.date}
                <small>{statusLabel(item.status)}</small>
              </li>
            ))}
          </ul>
        </aside>

        <Suspense fallback={<main className="map-shell" />}>
        <MapWorkspace
          envelopeA={layersA?.river_envelope}
          envelopeB={layersB?.river_envelope}
          leftA={layersA?.left_bank}
          rightA={layersA?.right_bank}
          leftB={layersB?.left_bank}
          rightB={layersB?.right_bank}
          centerline={centerline}
          sections={layersB?.cross_sections ?? layersA?.cross_sections}
          changes={comparison?.bank_changes}
          polygons={comparison?.change_polygons}
          showEnvelopeA={toggles.envelopeA}
          showEnvelopeB={toggles.envelopeB}
          showBanksA={toggles.banksA}
          showBanksB={toggles.banksB}
          showCenterline={toggles.centerline}
          showSections={toggles.sections}
          showChange={toggles.change}
          onSection={setSection}
        />
        </Suspense>

        <aside className="panel right">
          <p className="eyebrow">Reach statistics</p>
          <h2>{dateA && dateB ? `${dateA} → ${dateB}` : 'Select two dates'}</h2>
          <p className="note"><Radar size={13} /> Candidate change. Water level can mimic bank movement.</p>
          <div className="chart">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <XAxis dataKey="reach" tick={{ fontSize: 9 }} />
                <YAxis tick={{ fontSize: 9 }} />
                <Tooltip />
                <Line type="monotone" dataKey="widthA" stroke="#176d8d" dot={false} name="Width A" />
                <Line type="monotone" dataKey="widthB" stroke="#c56c48" dot={false} name="Width B" />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Reach</th>
                  <th>ΔL m</th>
                  <th>ΔR m</th>
                  <th>Max retreat</th>
                </tr>
              </thead>
              <tbody>
                {(comparison?.reach_statistics ?? []).slice(0, 12).map((row) => (
                  <tr key={row.reach_id}>
                    <td>{row.reach_id}</td>
                    <td>{row.mean_left_delta_m ?? '—'}</td>
                    <td>{row.mean_right_delta_m ?? '—'}</td>
                    <td>{row.max_retreat_m}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {section && (
            <div className="inspect">
              <MapPinned size={14} />
              <strong>Section {String(section.section_id ?? '')}</strong>
              <p>Chainage {String(section.chainage_m ?? '')} m</p>
              <p>Width {String(section.width_m ?? '—')} m · QC {String(section.qc_flag ?? '')}</p>
            </div>
          )}
        </aside>
      </div>

      <footer className="footer">
        <span>OSM + Esri basemap · Assam main stem only</span>
        <span>{study?.disclaimer}</span>
      </footer>
    </div>
  )
}
