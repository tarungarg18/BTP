import {
  Activity,
  Building2,
  ChevronRight,
  CloudRain,
  GraduationCap,
  Hospital,
  Layers3,
  Map,
  MapPin,
  Mountain,
  Route,
  School,
  ShieldAlert,
  SquareDashedMousePointer,
  Users,
  Waves,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import type {
  HazardMode,
  LayerState,
  RainfallScenario,
} from '../types/disaster'

interface LayerPanelProps {
  layers: LayerState
  baseMap: 'standard' | 'satellite'
  hazardMode: HazardMode
  compareHazards: boolean
  scenario: RainfallScenario
  onBaseMapChange: (value: 'standard' | 'satellite') => void
  onHazardModeChange: (value: HazardMode) => void
  onLayerToggle: (key: keyof LayerState) => void
  onCompareHazards: (value: boolean) => void
  onScenarioChange: (value: RainfallScenario) => void
  onSelectArea: () => void
}

interface ToggleRowProps {
  checked: boolean
  icon: LucideIcon
  label: string
  onChange: () => void
}

function ToggleRow({ checked, icon: Icon, label, onChange }: ToggleRowProps): React.JSX.Element {
  return (
    <button
      type="button"
      className={`layer-row ${checked ? 'layer-row-active' : ''}`}
      aria-pressed={checked}
      onClick={onChange}
    >
      <span className="layer-row-label">
        <Icon size={15} strokeWidth={1.8} aria-hidden="true" />
        {label}
      </span>
      <span className={`toggle ${checked ? 'toggle-on' : ''}`} aria-hidden="true">
        <span />
      </span>
    </button>
  )
}

function LayerPanel({
  layers,
  baseMap,
  hazardMode,
  compareHazards,
  scenario,
  onBaseMapChange,
  onHazardModeChange,
  onLayerToggle,
  onCompareHazards,
  onScenarioChange,
  onSelectArea,
}: LayerPanelProps): React.JSX.Element {
  return (
    <aside className="left-panel" aria-label="Map layers and tools">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Map workspace</p>
          <h2>Layers & analysis</h2>
        </div>
        <Layers3 size={18} aria-hidden="true" />
      </div>

      <button type="button" className="select-area-button" onClick={onSelectArea}>
        <SquareDashedMousePointer size={17} aria-hidden="true" />
        <span>
          <strong>Select area</strong>
          <small>Draw polygon or rectangle</small>
        </span>
        <ChevronRight size={16} aria-hidden="true" />
      </button>

      <section className="layer-section">
        <h3>Base map</h3>
        <div className="segmented-control">
          <button type="button" className={baseMap === 'standard' ? 'active' : ''} onClick={() => onBaseMapChange('standard')}>
            Standard
          </button>
          <button type="button" className={baseMap === 'satellite' ? 'active' : ''} onClick={() => onBaseMapChange('satellite')}>
            Satellite
          </button>
        </div>
      </section>

      <section className="layer-section">
        <h3>Hazard</h3>
        <div className="hazard-tabs">
          <button type="button" className={hazardMode === 'flood' ? 'active' : ''} onClick={() => onHazardModeChange('flood')}>Flood</button>
          <button type="button" className={hazardMode === 'landslide' ? 'active' : ''} onClick={() => onHazardModeChange('landslide')}>Landslide</button>
          <button type="button" className={hazardMode === 'combined' ? 'active' : ''} onClick={() => onHazardModeChange('combined')}>Combined</button>
        </div>
        <ToggleRow checked={layers.flood} icon={Waves} label="Flood risk zones" onChange={() => onLayerToggle('flood')} />
        <ToggleRow checked={layers.landslide} icon={Mountain} label="Landslide risk" onChange={() => onLayerToggle('landslide')} />
        <ToggleRow checked={layers.combined} icon={ShieldAlert} label="Combined risk" onChange={() => onLayerToggle('combined')} />
      </section>

      <section className="layer-section">
        <h3>Environment</h3>
        <ToggleRow checked={layers.rivers} icon={Waves} label="Rivers" onChange={() => onLayerToggle('rivers')} />
        <ToggleRow checked={layers.waterBodies} icon={MapPin} label="Water bodies" onChange={() => onLayerToggle('waterBodies')} />
        <ToggleRow checked={layers.elevation} icon={Mountain} label="Elevation" onChange={() => onLayerToggle('elevation')} />
        <ToggleRow checked={layers.slope} icon={Activity} label="Slope" onChange={() => onLayerToggle('slope')} />
        <ToggleRow checked={layers.rainfall} icon={CloudRain} label="Rainfall" onChange={() => onLayerToggle('rainfall')} />
      </section>

      <section className="layer-section">
        <h3>Infrastructure</h3>
        <ToggleRow checked={layers.roads} icon={Route} label="Road emphasis" onChange={() => onLayerToggle('roads')} />
        <ToggleRow checked={layers.buildings} icon={Building2} label="Built-up areas" onChange={() => onLayerToggle('buildings')} />
        <ToggleRow checked={layers.hospitals} icon={Hospital} label="Hospitals" onChange={() => onLayerToggle('hospitals')} />
        <ToggleRow checked={layers.schools} icon={GraduationCap} label="Education" onChange={() => onLayerToggle('schools')} />
        <ToggleRow checked={layers.bridges} icon={Map} label="Bridges" onChange={() => onLayerToggle('bridges')} />
      </section>

      <section className="layer-section">
        <h3>Exposure</h3>
        <ToggleRow checked={layers.population} icon={Users} label="Population" onChange={() => onLayerToggle('population')} />
        <ToggleRow checked={layers.criticalInfrastructure} icon={School} label="Critical assets" onChange={() => onLayerToggle('criticalInfrastructure')} />
      </section>

      <section className="scenario-card">
        <div className="scenario-title">
          <div>
            <p className="eyebrow">Illustrative simulation</p>
            <h3>Rainfall scenario</h3>
          </div>
          <CloudRain size={17} aria-hidden="true" />
        </div>
        <select value={scenario} onChange={(event) => onScenarioChange(event.target.value as RainfallScenario)} aria-label="Rainfall scenario">
          <option>Normal</option>
          <option>Heavy Rain</option>
          <option>Extreme Rain</option>
        </select>
        <label className="compare-row">
          <span>Compare hazards</span>
          <input type="checkbox" checked={compareHazards} onChange={(event) => onCompareHazards(event.target.checked)} />
        </label>
      </section>

      <p className="source-note">
        OpenStreetMap basemap. Scientific overlays and risk values are demo data.
      </p>
    </aside>
  )
}

export default LayerPanel
