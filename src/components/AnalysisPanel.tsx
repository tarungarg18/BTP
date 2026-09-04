import { useState } from 'react'
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Building2,
  CheckCircle2,
  ChevronRight,
  CloudRain,
  Database,
  Droplets,
  GraduationCap,
  Hospital,
  Loader2,
  MapPinned,
  Mountain,
  Navigation,
  Route,
  Sparkles,
  Users,
  Waves,
  X,
} from 'lucide-react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type {
  AreaAnalysis,
  DrawnGeometry,
  HistoricalEvent,
  RainfallScenario,
  RiskLevel,
} from '../types/disaster'

interface AnalysisPanelProps {
  analysis: AreaAnalysis | null
  drawnGeometry: DrawnGeometry | null
  loading: boolean
  scenario: RainfallScenario
  onAnalyze: () => void
  onClear: () => void
}

type AnalysisTab = 'overview' | 'history' | 'model'

function levelClass(level: RiskLevel): string {
  return level.toLowerCase().replace(' ', '-')
}

function AnalysisPanel({
  analysis,
  drawnGeometry,
  loading,
  scenario,
  onAnalyze,
  onClear,
}: AnalysisPanelProps): React.JSX.Element {
  const [activeTab, setActiveTab] = useState<AnalysisTab>('overview')
  const [selectedEvent, setSelectedEvent] = useState<HistoricalEvent | null>(null)

  if (!analysis && !drawnGeometry) {
    return (
      <aside className="analysis-panel analysis-empty" aria-label="Area analysis">
        <div className="empty-visual">
          <MapPinned size={30} strokeWidth={1.5} aria-hidden="true" />
          <span />
        </div>
        <p className="eyebrow">Area intelligence</p>
        <h2>Select an area to begin analysis</h2>
        <p>
          Draw a polygon or select a demo risk zone to inspect terrain, hazard,
          history, model factors, and potential exposure.
        </p>
        <div className="empty-flow" aria-label="Analysis workflow">
          <span>Area</span><ChevronRight size={13} /><span>GIS</span><ChevronRight size={13} /><span>Risk</span><ChevronRight size={13} /><span>Decision</span>
        </div>
        <div className="empty-capabilities">
          <div><Mountain size={15} />Elevation & slope</div>
          <div><CloudRain size={15} />Rainfall scenario</div>
          <div><Waves size={15} />River proximity</div>
          <div><BarChart3 size={15} />Historical trends</div>
        </div>
        <p className="honesty-note">
          <AlertTriangle size={14} />
          Prototype outputs are illustrative, not operational forecasts.
        </p>
      </aside>
    )
  }

  if (!analysis && drawnGeometry) {
    return (
      <aside className="analysis-panel selection-ready" aria-label="Selected area">
        <button type="button" className="panel-close" onClick={onClear} aria-label="Clear selected area"><X size={18} /></button>
        <div className="selection-icon"><CheckCircle2 size={26} /></div>
        <p className="eyebrow">Geometry captured</p>
        <h2>Selected area</h2>
        <div className="selection-area-value">
          <strong>{drawnGeometry.areaKm2.toFixed(2)}</strong>
          <span>km² approximate map area</span>
        </div>
        <div className="geometry-ready">
          <Database size={16} />
          Polygon coordinates and bounding geometry are ready for analysis.
        </div>
        <button type="button" className="analyze-button" onClick={onAnalyze} disabled={loading}>
          {loading ? <Loader2 size={17} className="animate-spin" /> : <Sparkles size={17} />}
          {loading ? 'Analyzing demo features…' : 'Analyze area'}
        </button>
        <button type="button" className="clear-button" onClick={onClear}>Clear selection</button>
        <p className="source-note">Demo analysis simulates the future POST /api/analyze-area workflow.</p>
      </aside>
    )
  }

  if (!analysis) return <aside className="analysis-panel" />

  const comparisonData = [
    { hazard: 'Flood', value: analysis.floodRisk, color: '#317f9e' },
    { hazard: 'Landslide', value: analysis.landslideRisk, color: '#a06c43' },
  ]

  return (
    <aside className="analysis-panel" aria-label="Selected area analysis">
      <div className="analysis-top">
        <div>
          <p className="eyebrow">Selected area · demo output</p>
          <h2>{analysis.name}</h2>
          <span>{analysis.areaKm2.toFixed(2)} km² analyzed</span>
        </div>
        <button type="button" className="panel-close" onClick={onClear} aria-label="Close analysis"><X size={18} /></button>
      </div>

      <div className="risk-cards">
        <article className="risk-card flood">
          <div><Droplets size={16} /><span>Flood risk</span></div>
          <strong>{analysis.floodRisk}%</strong>
          <small className={levelClass(analysis.floodRisk >= 80 ? 'Very High' : analysis.floodRisk >= 65 ? 'High' : 'Moderate')}>
            {analysis.floodRisk >= 80 ? 'Very high' : analysis.floodRisk >= 65 ? 'High' : 'Moderate'}
          </small>
        </article>
        <article className="risk-card landslide">
          <div><Mountain size={16} /><span>Landslide</span></div>
          <strong>{analysis.landslideRisk}%</strong>
          <small className={levelClass(analysis.landslideRisk >= 65 ? 'High' : analysis.landslideRisk >= 40 ? 'Moderate' : 'Low')}>
            {analysis.landslideRisk >= 65 ? 'High' : analysis.landslideRisk >= 40 ? 'Moderate' : 'Low'}
          </small>
        </article>
        <article className="risk-card overall">
          <div><Activity size={16} /><span>Overall</span></div>
          <strong>{analysis.overallRisk}</strong>
          <small>Illustrative</small>
        </article>
      </div>

      <div className="analysis-tabs" role="tablist" aria-label="Analysis sections">
        <button type="button" role="tab" aria-selected={activeTab === 'overview'} className={activeTab === 'overview' ? 'active' : ''} onClick={() => setActiveTab('overview')}>Overview</button>
        <button type="button" role="tab" aria-selected={activeTab === 'history'} className={activeTab === 'history' ? 'active' : ''} onClick={() => setActiveTab('history')}>History</button>
        <button type="button" role="tab" aria-selected={activeTab === 'model'} className={activeTab === 'model' ? 'active' : ''} onClick={() => setActiveTab('model')}>Model</button>
      </div>

      {activeTab === 'overview' && (
        <div className="analysis-content">
          <section className="analysis-section">
            <div className="section-title"><h3>Environmental profile</h3><span>Demo</span></div>
            <div className="metric-grid">
              <article><Mountain size={15} /><span>Elevation avg.</span><strong>{analysis.elevation.average} m</strong><small>{analysis.elevation.minimum}–{analysis.elevation.maximum} m</small></article>
              <article><Activity size={15} /><span>Average slope</span><strong>{analysis.slope}°</strong><small>Terrain estimate</small></article>
              <article><CloudRain size={15} /><span>24h rainfall</span><strong>{analysis.rainfall.daily} mm</strong><small>{analysis.rainfall.weekly} mm / 7d</small></article>
              <article><Navigation size={15} /><span>River distance</span><strong>{analysis.river.distanceKm} km</strong><small>{analysis.river.name}</small></article>
            </div>
            <dl className="details-list">
              <div><dt>Drainage density</dt><dd>{analysis.drainageDensity} km/km²</dd></div>
              <div><dt>Soil</dt><dd>{analysis.soil}</dd></div>
              <div><dt>Dominant land use</dt><dd>Built-up {analysis.landUse.builtUp}%</dd></div>
            </dl>
          </section>

          <section className="analysis-section river-section">
            <div className="section-title"><h3>River intelligence</h3><Waves size={17} /></div>
            <div className="river-primary">
              <div className="river-icon"><Waves size={21} /></div>
              <div><span>Nearest river</span><strong>{analysis.river.name}</strong></div>
              <b>{analysis.river.distanceKm} km</b>
            </div>
            <dl className="details-list">
              <div><dt>Historical flood association</dt><dd className="high-text">{analysis.river.floodAssociation}</dd></div>
              <div><dt>Floodplain proximity</dt><dd>{analysis.river.floodplainClass}</dd></div>
              <div><dt>Water level / gauge</dt><dd>Future integration</dd></div>
            </dl>
          </section>

          <section className="analysis-section">
            <div className="section-title"><h3>Potential exposure</h3><span>Demo</span></div>
            <div className="exposure-grid">
              <div><Users size={15} /><strong>{analysis.exposure.population.toLocaleString()}</strong><span>People</span></div>
              <div><Building2 size={15} /><strong>{analysis.exposure.buildings.toLocaleString()}</strong><span>Buildings</span></div>
              <div><Hospital size={15} /><strong>{analysis.exposure.hospitals}</strong><span>Hospitals</span></div>
              <div><GraduationCap size={15} /><strong>{analysis.exposure.schools}</strong><span>Schools</span></div>
              <div><Route size={15} /><strong>{analysis.exposure.roadsKm} km</strong><span>Roads</span></div>
            </div>
          </section>

          <section className="analysis-section">
            <div className="section-title"><h3>Hazard comparison</h3><span>{scenario}</span></div>
            <div className="chart-small">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={comparisonData} layout="vertical" margin={{ top: 4, right: 16, bottom: 0, left: 2 }}>
                  <CartesianGrid stroke="#e6e8e6" horizontal={false} />
                  <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 10 }} />
                  <YAxis type="category" dataKey="hazard" width={66} tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
                  <Tooltip formatter={(value) => [`${value}%`, 'Probability']} />
                  <Bar dataKey="value" radius={[0, 3, 3, 0]} barSize={14}>
                    {comparisonData.map((item) => <Cell key={item.hazard} fill={item.color} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>
        </div>
      )}

      {activeTab === 'history' && (
        <div className="analysis-content">
          <section className="analysis-section">
            <div className="section-title"><h3>Historical events</h3><span>Demo dataset</span></div>
            <div className="history-list">
              {analysis.history.map((event) => (
                <button type="button" key={event.id} className={selectedEvent?.id === event.id ? 'active' : ''} onClick={() => setSelectedEvent(event)}>
                  <strong>{event.year}</strong>
                  <i className={event.type.toLowerCase()} />
                  <span><b>{event.type} event</b><small>Severity: {event.severity}</small></span>
                  <ChevronRight size={14} />
                </button>
              ))}
            </div>
            {selectedEvent && <div className="event-detail"><strong>{selectedEvent.year} · {selectedEvent.type}</strong><p>{selectedEvent.detail}</p></div>}
          </section>

          <section className="analysis-section">
            <div className="section-title"><h3>Flood incidents by year</h3><span>Hover for values</span></div>
            <div className="chart-medium">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={analysis.trends}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e6e8e6" vertical={false} />
                  <XAxis dataKey="year" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 10 }} axisLine={false} tickLine={false} width={22} />
                  <Tooltip />
                  <Bar dataKey="floodIncidents" name="Flood incidents" fill="#4385a0" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="analysis-section">
            <div className="section-title"><h3>Rainfall trend</h3><span>Illustrative mm</span></div>
            <div className="chart-medium">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={analysis.trends}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e6e8e6" vertical={false} />
                  <XAxis dataKey="year" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 10 }} axisLine={false} tickLine={false} width={30} />
                  <Tooltip formatter={(value) => [`${value} mm`, 'Rainfall']} />
                  <Line type="monotone" dataKey="rainfall" stroke="#287c91" strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="analysis-section">
            <div className="section-title"><h3>Risk trend over time</h3><span>Demo index</span></div>
            <div className="chart-medium">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={analysis.trends}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e6e8e6" vertical={false} />
                  <XAxis dataKey="year" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} width={26} />
                  <Tooltip formatter={(value) => [`${value}%`, 'Risk index']} />
                  <Area type="monotone" dataKey="risk" stroke="#c56c48" fill="#e8b69f" fillOpacity={0.48} strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </section>
        </div>
      )}

      {activeTab === 'model' && (
        <div className="analysis-content">
          <section className="analysis-section">
            <div className="section-title"><h3>Why this area is at risk</h3><span>Demo explanation</span></div>
            <div className="factor-list">
              {analysis.modelExplanation.map((item) => (
                <div key={item.factor}>
                  <span><b>{item.factor}</b><small>{Math.round(item.contribution * 100)}%</small></span>
                  <i><em style={{ width: `${item.contribution * 100 * 2.6}%` }} /></i>
                </div>
              ))}
            </div>
            <p className="method-note">Structured for future SHAP factor contributions from the prediction API.</p>
          </section>

          <section className="analysis-section model-output">
            <div className="section-title"><h3>Model output</h3><span>Prototype</span></div>
            <div className="model-probabilities">
              <div><span>Flood probability</span><strong>{analysis.floodRisk}%</strong></div>
              <div><span>Landslide probability</span><strong>{analysis.landslideRisk}%</strong></div>
              <div><span>Demo confidence score</span><strong>{analysis.confidence}%</strong></div>
            </div>
            <dl className="details-list">
              <div><dt>Model</dt><dd>Demo XGBoost interface</dd></div>
              <div><dt>Data</dt><dd>Simulated environmental features</dd></div>
            </dl>
            <p className="honesty-note"><AlertTriangle size={14} />No trained model is running. Actual model output will be connected in the next phase.</p>
          </section>

          <section className="analysis-section next-phase">
            <div className="section-title"><h3>Next phase integration</h3></div>
            <ul>
              <li><CheckCircle2 size={14} />Real historical disaster data</li>
              <li><CheckCircle2 size={14} />DEM-derived elevation & slope</li>
              <li><CheckCircle2 size={14} />Live rainfall and river gauges</li>
              <li><CheckCircle2 size={14} />ML prediction & SHAP</li>
              <li><CheckCircle2 size={14} />Population exposure & alerts</li>
            </ul>
          </section>
        </div>
      )}
    </aside>
  )
}

export default AnalysisPanel
