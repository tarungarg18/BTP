import { lazy, Suspense, useCallback, useMemo, useState } from 'react'
import {
  AlertCircle,
  ChevronDown,
  Info,
  Layers3,
  Loader2,
  LocateFixed,
  Menu,
  Search,
  ShieldCheck,
  X,
} from 'lucide-react'

import LayerPanel from './components/LayerPanel'
import { defaultLayers, searchPlaces } from './data/demoData'
import {
  analyzeArea,
  analyzeRiskZone,
  getScenarioFloodRisk,
} from './services/disasterApi'
import type {
  AreaAnalysis,
  DrawnGeometry,
  HazardMode,
  LayerState,
  RainfallScenario,
  RiskZoneFeature,
  SearchPlace,
} from './types/disaster'

const AnalysisPanel = lazy(() => import('./components/AnalysisPanel'))
const MapView = lazy(() => import('./components/MapView'))

function MapLoading(): React.JSX.Element {
  return (
    <main className="map-shell map-loading" aria-label="Loading interactive map">
      <div>
        <Loader2 size={23} className="animate-spin" aria-hidden="true" />
        <strong>Loading GIS workspace</strong>
        <span>Preparing local layers and map controls…</span>
      </div>
    </main>
  )
}

function PanelLoading(): React.JSX.Element {
  return (
    <aside className="analysis-panel panel-loading" aria-label="Loading analysis tools">
      <Loader2 size={20} className="animate-spin" aria-hidden="true" />
      <span>Loading analysis tools…</span>
    </aside>
  )
}

function App(): React.JSX.Element {
  const [layers, setLayers] = useState<LayerState>({ ...defaultLayers })
  const [baseMap, setBaseMap] = useState<'standard' | 'satellite'>('standard')
  const [hazardMode, setHazardMode] = useState<HazardMode>('flood')
  const [compareHazards, setCompareHazards] = useState(false)
  const [scenario, setScenario] = useState<RainfallScenario>('Heavy Rain')
  const [drawSignal, setDrawSignal] = useState(0)
  const [resetSignal, setResetSignal] = useState(0)
  const [drawnGeometry, setDrawnGeometry] = useState<DrawnGeometry | null>(null)
  const [analysis, setAnalysis] = useState<AreaAnalysis | null>(null)
  const [loading, setLoading] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchTarget, setSearchTarget] = useState<SearchPlace | null>(null)
  const [leftOpen, setLeftOpen] = useState(false)
  const [rightOpen, setRightOpen] = useState(false)
  const [showInfo, setShowInfo] = useState(false)

  const searchResults = useMemo(() => {
    const query = searchQuery.trim().toLowerCase()
    if (!query) return []
    return searchPlaces
      .filter((place) => `${place.name} ${place.detail}`.toLowerCase().includes(query))
      .slice(0, 5)
  }, [searchQuery])

  const handleGeometryDrawn = useCallback((geometry: DrawnGeometry): void => {
    setDrawnGeometry(geometry)
    setAnalysis(null)
    setRightOpen(true)
  }, [])

  const handleLayerToggle = (key: keyof LayerState): void => {
    setLayers((current) => ({ ...current, [key]: !current[key] }))
  }

  const handleHazardModeChange = (mode: HazardMode): void => {
    setHazardMode(mode)
    setLayers((current) => ({
      ...current,
      flood: mode === 'flood',
      landslide: mode === 'landslide',
      combined: mode === 'combined',
    }))
  }

  const handleAnalyze = async (): Promise<void> => {
    if (!drawnGeometry) return
    setLoading(true)
    const result = await analyzeArea(drawnGeometry, scenario)
    setAnalysis(result)
    setLoading(false)
  }

  const handleAnalyzeZone = useCallback(async (zone: RiskZoneFeature): Promise<void> => {
    setLoading(true)
    setDrawnGeometry(null)
    setRightOpen(true)
    const result = await analyzeRiskZone(zone, scenario)
    setAnalysis(result)
    setLoading(false)
  }, [scenario])

  const handleScenarioChange = (value: RainfallScenario): void => {
    setScenario(value)
    setAnalysis((current) => {
      if (!current) return current
      const floodRisk = getScenarioFloodRisk(value)
      return {
        ...current,
        floodRisk,
        overallRisk: floodRisk >= 78 ? 'High' : floodRisk >= 50 ? 'Moderate' : 'Low',
      }
    })
  }

  const handleClear = (): void => {
    setDrawnGeometry(null)
    setAnalysis(null)
    setResetSignal((value) => value + 1)
    setRightOpen(false)
  }

  const handleReset = (): void => {
    setLayers({ ...defaultLayers })
    setBaseMap('standard')
    setHazardMode('flood')
    setCompareHazards(false)
    setScenario('Heavy Rain')
    setSearchQuery('')
    setSearchTarget(null)
    setDrawnGeometry(null)
    setAnalysis(null)
    setResetSignal((value) => value + 1)
    setLeftOpen(false)
    setRightOpen(false)
  }

  const handleSearchSelection = (place: SearchPlace): void => {
    setSearchTarget({ ...place })
    setSearchQuery(place.name)
  }

  return (
    <div className="app-shell">
      <header className="top-header">
        <div className="brand">
          <div className="brand-mark"><ShieldCheck size={22} strokeWidth={1.8} /></div>
          <div>
            <h1>Guwahati Disaster Intelligence</h1>
            <span>GIS-based Hazard Analysis & Risk Visualization</span>
          </div>
        </div>

        <div className="search-wrap">
          <Search size={17} aria-hidden="true" />
          <input
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Search Guwahati location..."
            aria-label="Search prototype locations"
          />
          {searchQuery && <button type="button" onClick={() => setSearchQuery('')} aria-label="Clear search"><X size={15} /></button>}
          {searchResults.length > 0 && (
            <div className="search-results">
              <p>Prototype local search</p>
              {searchResults.map((place) => (
                <button type="button" key={place.name} onClick={() => handleSearchSelection(place)}>
                  <LocateFixed size={15} />
                  <span><strong>{place.name}</strong><small>{place.detail}</small></span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="header-actions">
          <span className="demo-badge"><i />DEMO DATA</span>
          <button type="button" className="header-button" onClick={() => setLeftOpen((value) => !value)}><Layers3 size={16} />Layers</button>
          <button type="button" className="icon-button" onClick={() => setShowInfo((value) => !value)} aria-label="About demo data"><Info size={18} /></button>
          <button type="button" className="mobile-menu" onClick={() => setLeftOpen((value) => !value)} aria-label="Open layers"><Menu size={20} /></button>
        </div>
      </header>

      {showInfo && (
        <div className="info-popover">
          <strong>Academically honest prototype</strong>
          <p>OpenStreetMap provides the real basemap. Hazard, terrain, rainfall, exposure, and model outputs are illustrative local demo data.</p>
          <button type="button" onClick={() => setShowInfo(false)}>Understood</button>
        </div>
      )}

      <div className="workspace">
        <div className={`left-panel-wrap ${leftOpen ? 'open' : ''}`}>
          <LayerPanel
            layers={layers}
            baseMap={baseMap}
            hazardMode={hazardMode}
            compareHazards={compareHazards}
            scenario={scenario}
            onBaseMapChange={setBaseMap}
            onHazardModeChange={handleHazardModeChange}
            onLayerToggle={handleLayerToggle}
            onCompareHazards={setCompareHazards}
            onScenarioChange={handleScenarioChange}
            onSelectArea={() => {
              setDrawSignal((value) => value + 1)
              setLeftOpen(false)
            }}
          />
        </div>

        <Suspense fallback={<MapLoading />}>
          <MapView
            layers={layers}
            baseMap={baseMap}
            hazardMode={hazardMode}
            compareHazards={compareHazards}
            drawSignal={drawSignal}
            resetSignal={resetSignal}
            searchTarget={searchTarget}
            onGeometryDrawn={handleGeometryDrawn}
            onAnalyzeZone={(zone) => void handleAnalyzeZone(zone)}
          />
        </Suspense>

        <div className={`right-panel-wrap ${rightOpen ? 'open' : ''}`}>
          <Suspense fallback={<PanelLoading />}>
            <AnalysisPanel
              analysis={analysis}
              drawnGeometry={drawnGeometry}
              loading={loading}
              scenario={scenario}
              onAnalyze={() => void handleAnalyze()}
              onClear={handleClear}
            />
          </Suspense>
        </div>
      </div>

      <footer className="status-bar">
        <div><span className="status-live" />Prototype operational</div>
        <div className="status-location">26.1445° N, 91.7362° E <ChevronDown size={12} /></div>
        <div>OSM basemap <span>·</span> Illustrative overlays <span>·</span> No live warning data</div>
        <button type="button" onClick={handleReset}>Reset map</button>
      </footer>

      <button type="button" className="mobile-analysis-trigger" onClick={() => setRightOpen(true)}>
        <AlertCircle size={16} />
        {analysis ? `${analysis.overallRisk} hazard` : drawnGeometry ? 'Area ready' : 'Area analysis'}
      </button>
    </div>
  )
}

export default App
