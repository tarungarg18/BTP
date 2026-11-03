import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, GitCompare, Loader2, MapPinned, Waves } from 'lucide-react'
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { api } from './api'
import type { Acquisition, Comparison, EpochSummary, ReachStat, StudyArea } from './types'

const MapWorkspace = lazy(() => import('./MapWorkspace'))

function statusLabel(status: string): string {
  return status.replaceAll('_', ' ')
}

export default function App(): React.JSX.Element {
  const [study, setStudy] = useState<StudyArea | null>(null)
  const [epochs, setEpochs] = useState<EpochSummary[]>([])
  const [acquisitions, setAcquisitions] = useState<Acquisition[]>([])
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
    waterA: true,
    waterB: true,
    banksA: false,
    banksB: true,
    centerline: true,
    sections: false,
    change: true,
  })

  useEffect(() => {
    void (async () => {
      try {
        const [area, list, reference, acqs] = await Promise.all([
          api.studyArea(),
          api.epochs(),
          api.reference(),
          api.acquisitions(),
        ])
        setStudy(area)
        setEpochs(list)
        setAcquisitions(acqs)
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
      km: Math.round(row.chainage_start_m / 1000),
      widthA: row.mean_width_a_m,
      widthB: row.mean_width_b_m,
    })) ?? []

  if (error) {
    return (
      <div className="fatal">
        <AlertTriangle />
        <p>The portal could not load satellite water yet.</p>
        <small>{error}</small>
        <small>On the server run: python -m processing.ingest</small>
      </div>
    )
  }

  return (
    <div className="shell">
      <header className="header">
        <div className="brand">
          <Waves size={20} />
          <div>
            <h1>Brahmaputra bank change</h1>
            <span>Assam main stem · Sadiya to Dhubri · satellite water, not a field survey</span>
          </div>
        </div>
        <div className="header-meta">
          <span className="badge">CANDIDATE CHANGE ONLY</span>
          <span>{study ? `${(study.corridor_length_m / 1000).toFixed(0)} km` : '…'}</span>
          {loading && <Loader2 className="spin" size={16} />}
        </div>
      </header>

      <div className="workspace">
        <aside className="panel left">
          <p className="read-me">
            You are looking at <strong>real Sentinel water</strong> on the satellite photo.
            If a line leaves the visible river, it is wrong. The old white tube was a
            search corridor, not the Brahmaputra — that overlay has been removed.
          </p>
          <button type="button" className="primary" onClick={latestVsPrevious}>
            <GitCompare size={15} /> Latest vs previous date
          </button>
          <label>
            Earlier date
            <select value={dateA} onChange={(event) => setDateA(event.target.value)}>
              {processed.map((item) => (
                <option key={item.id} value={item.date}>
                  {item.date} · {item.sensors.join(', ')} · {item.scene_count ?? '?'} scenes
                </option>
              ))}
            </select>
          </label>
          <label>
            Later date
            <select value={dateB} onChange={(event) => setDateB(event.target.value)}>
              {processed.map((item) => (
                <option key={item.id} value={item.date}>
                  {item.date} · {item.sensors.join(', ')} · {item.scene_count ?? '?'} scenes
                </option>
              ))}
            </select>
          </label>

          <p className="eyebrow">Show on the map</p>
          {(
            [
              ['waterA', 'Water on earlier date'],
              ['waterB', 'Water on later date'],
              ['banksA', 'Banks, earlier date'],
              ['banksB', 'Banks, later date (looking downstream)'],
              ['centerline', 'Channel centre'],
              ['sections', 'Width ticks (every 900 m)'],
              ['change', 'Where the outer water moved'],
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

          <p className="eyebrow">How this is calculated</p>
          <ol className="how">
            {(study?.how_calculated ?? []).map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ol>
          <p className="note source">{study?.source}</p>

          <p className="eyebrow">Scenes used</p>
          <ul className="status-list">
            {(acquisitions.length ? acquisitions : epochs).map((item) => (
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
            waterA={layersA?.river_only}
            waterB={layersB?.river_only}
            leftA={layersA?.left_bank}
            rightA={layersA?.right_bank}
            leftB={layersB?.left_bank}
            rightB={layersB?.right_bank}
            centerline={centerline}
            sections={layersB?.cross_sections ?? layersA?.cross_sections}
            polygons={comparison?.change_polygons}
            endpoints={study?.endpoints}
            revision={`${dateA}__${dateB}`}
            showWaterA={toggles.waterA}
            showWaterB={toggles.waterB}
            showBanksA={toggles.banksA}
            showBanksB={toggles.banksB}
            showCenterline={toggles.centerline}
            showSections={toggles.sections}
            showChange={toggles.change}
            onSection={setSection}
          />
        </Suspense>

        <aside className="panel right">
          <p className="eyebrow">Width along the river</p>
          <h2>{dateA && dateB ? `${dateA}  →  ${dateB}` : 'Select two dates'}</h2>
          <p className="note">
            Positive bank shift = water edge moved outward (candidate erosion).
            A higher river stage can look the same. This is not a warning product.
          </p>
          <div className="chart">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <XAxis dataKey="km" tick={{ fontSize: 9 }} label={{ value: 'km from Sadiya', fontSize: 10, position: 'insideBottom', offset: -2 }} />
                <YAxis tick={{ fontSize: 9 }} />
                <Tooltip />
                <Line type="monotone" dataKey="widthA" stroke="#176d8d" dot={false} name="Width earlier (m)" />
                <Line type="monotone" dataKey="widthB" stroke="#c56c48" dot={false} name="Width later (m)" />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>km</th>
                  <th>Width A</th>
                  <th>Width B</th>
                  <th>Left Δ m</th>
                  <th>Right Δ m</th>
                </tr>
              </thead>
              <tbody>
                {(comparison?.reach_statistics ?? []).slice(0, 16).map((row) => (
                  <tr key={row.reach_id}>
                    <td>{Math.round(row.chainage_start_m / 1000)}</td>
                    <td>{row.mean_width_a_m ?? '—'}</td>
                    <td>{row.mean_width_b_m ?? '—'}</td>
                    <td>{row.mean_left_delta_m ?? '—'}</td>
                    <td>{row.mean_right_delta_m ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {section && (
            <div className="inspect">
              <MapPinned size={14} />
              <strong>{String(section.section_id ?? 'Section')}</strong>
              <p>{Math.round(Number(section.chainage_m ?? 0) / 1000)} km from Sadiya</p>
              <p>
                Width {String(section.width_a_m ?? section.width_m ?? '—')} m
                {section.width_b_m != null ? ` → ${String(section.width_b_m)} m` : ''}
              </p>
            </div>
          )}
        </aside>
      </div>

      <footer className="footer">
        <span>Esri imagery · click a width tick to inspect</span>
        <span>{study?.disclaimer}</span>
      </footer>
    </div>
  )
}
