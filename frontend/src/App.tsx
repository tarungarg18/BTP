import { Download, Loader2, Waves } from 'lucide-react'
import { useEffect, useState } from 'react'

import { api } from './api'
import AnalysisView from './AnalysisView'
import type { PortalSummary, ViewId } from './types'

interface PeriodRow {
  id: string
  label: string | null
  water_display: string | null
  scene_count: number | null
  file: string | null
  png: string
}

function Downloads(): React.JSX.Element {
  const [rows, setRows] = useState<PeriodRow[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void api.periods().then(setRows).catch((err: unknown) => {
      setError(err instanceof Error ? err.message : 'Extract list failed')
    })
  }, [])

  return (
    <div className="library">
      <h2>Downloads</h2>
      <p className="note">GeoTIFFs fetched from Earth Engine for the dates you compare, then stored here. Optical files are Sentinel-2. Microwave files are Sentinel-1.</p>
      {error && <p className="note">{error}</p>}
      {rows.length === 0 && !error && <p className="note">No extract yet. Choose a date on Change and the file will appear here.</p>}
      {rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Period</th><th>Water</th><th>Scenes</th><th>Files</th></tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{row.label}</td>
                  <td>{row.water_display}</td>
                  <td>{row.scene_count ?? '—'}</td>
                  <td><a href={row.png}>PNG</a>{row.file && <> · <a href={row.file}>GeoTIFF</a></>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default function App(): React.JSX.Element {
  const [view, setView] = useState<ViewId>('analysis')
  const [summary, setSummary] = useState<PortalSummary | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void api.summary().then(setSummary).catch((err: unknown) => {
      setError(err instanceof Error ? err.message : 'The portal API did not respond')
    })
  }, [])

  return (
    <div className="shell">
      <header className="header">
        <div className="brand">
          <div className="mark"><Waves size={16} /></div>
          <div>
            <h1>Brahmaputra</h1>
            <p>Assam corridor</p>
          </div>
        </div>
        <span className="count">Earth Engine</span>
        <nav className="nav">
          <button type="button" className={view === 'analysis' ? 'active' : ''} onClick={() => setView('analysis')}>Change</button>
          <button type="button" className={view === 'data' ? 'active' : ''} onClick={() => setView('data')}><Download size={15} /> Downloads</button>
        </nav>
      </header>
      {error && <div className="fatal"><p>{error}</p></div>}
      {!error && !summary && (
        <div className="loading-screen"><Loader2 className="spin" size={22} /><p>Loading masks</p></div>
      )}
      {summary && view === 'analysis' && <AnalysisView summary={summary} />}
      {summary && view === 'data' && <Downloads />}
    </div>
  )
}
