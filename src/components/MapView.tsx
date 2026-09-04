import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Circle,
  CircleMarker,
  GeoJSON,
  MapContainer,
  Polygon,
  Popup,
  ScaleControl,
  TileLayer,
  Tooltip,
  ZoomControl,
  useMap,
} from 'react-leaflet'
import {
  Crosshair,
  Expand,
  Home,
  Hospital,
  School,
} from 'lucide-react'
import L, {
  type GeoJSON as LeafletGeoJSON,
  type PathOptions,
  type StyleFunction,
} from 'leaflet'
import 'leaflet-draw'
import 'leaflet/dist/leaflet.css'
import 'leaflet-draw/dist/leaflet.draw.css'

import {
  GUWAHATI_BOUNDS,
  GUWAHATI_CENTER,
  brahmaputraRiver,
  infrastructure,
  riskZones,
  waterBodies,
} from '../data/demoData'
import type {
  DrawnGeometry,
  HazardMode,
  LayerState,
  RiskLevel,
  RiskZoneFeature,
  SearchPlace,
} from '../types/disaster'

interface MapViewProps {
  layers: LayerState
  baseMap: 'standard' | 'satellite'
  hazardMode: HazardMode
  compareHazards: boolean
  drawSignal: number
  resetSignal: number
  searchTarget: SearchPlace | null
  onGeometryDrawn: (geometry: DrawnGeometry) => void
  onAnalyzeZone: (zone: RiskZoneFeature) => void
}

interface MapControllerProps {
  drawSignal: number
  resetSignal: number
  searchTarget: SearchPlace | null
  onGeometryDrawn: (geometry: DrawnGeometry) => void
}

const STANDARD_TILES = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
const SATELLITE_TILES = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'

function riskLevel(value: number): RiskLevel {
  if (value >= 80) return 'Very High'
  if (value >= 65) return 'High'
  if (value >= 45) return 'Moderate'
  return 'Low'
}

function riskColor(value: number): string {
  if (value >= 80) return '#b83b3b'
  if (value >= 65) return '#dd7246'
  if (value >= 45) return '#d4a72c'
  return '#4d8b65'
}

function MapController({
  drawSignal,
  resetSignal,
  searchTarget,
  onGeometryDrawn,
}: MapControllerProps): null {
  const map = useMap()
  const drawnItemsRef = useRef<L.FeatureGroup>(new L.FeatureGroup())
  const activeDrawerRef = useRef<L.Draw.Polygon | null>(null)

  useEffect(() => {
    const drawnItems = drawnItemsRef.current
    map.addLayer(drawnItems)
    const drawControl = new L.Control.Draw({
      position: 'topright',
      edit: { featureGroup: drawnItems, remove: true },
      draw: {
        polygon: {
          allowIntersection: false,
          shapeOptions: { color: '#0c6b68', weight: 2, fillOpacity: 0.16 },
        },
        rectangle: { shapeOptions: { color: '#0c6b68', weight: 2, fillOpacity: 0.16 } },
        polyline: false,
        circle: false,
        circlemarker: false,
        marker: false,
      },
    })
    map.addControl(drawControl)

    const handleCreated = (leafletEvent: L.LeafletEvent): void => {
      const event = leafletEvent as L.DrawEvents.Created
      drawnItems.clearLayers()
      drawnItems.addLayer(event.layer)
      const feature = event.layer.toGeoJSON()
      if (feature.geometry.type !== 'Polygon') return
      const latLngs = (event.layer as L.Polygon).getLatLngs()[0] as L.LatLng[]
      const areaKm2 = L.GeometryUtil.geodesicArea(latLngs) / 1_000_000
      onGeometryDrawn({ feature, areaKm2 })
    }

    map.on(L.Draw.Event.CREATED, handleCreated)
    return () => {
      map.off(L.Draw.Event.CREATED, handleCreated)
      map.removeControl(drawControl)
      map.removeLayer(drawnItems)
    }
  }, [map, onGeometryDrawn])

  useEffect(() => {
    if (drawSignal === 0) return
    activeDrawerRef.current?.disable()
    activeDrawerRef.current = new L.Draw.Polygon(map as L.DrawMap, {
      allowIntersection: false,
      showArea: true,
      shapeOptions: { color: '#0c6b68', weight: 2, fillOpacity: 0.16 },
    })
    activeDrawerRef.current.enable()
  }, [drawSignal, map])

  useEffect(() => {
    if (resetSignal === 0) return
    drawnItemsRef.current.clearLayers()
    map.fitBounds(GUWAHATI_BOUNDS, { padding: [16, 16] })
    map.closePopup()
  }, [map, resetSignal])

  useEffect(() => {
    if (!searchTarget) return
    map.flyTo(searchTarget.coordinates, searchTarget.zoom, { duration: 0.9 })
  }, [map, searchTarget])

  return null
}

function FullscreenButton(): React.JSX.Element {
  const map = useMap()
  const [fullscreen, setFullscreen] = useState(false)

  const toggleFullscreen = async (): Promise<void> => {
    const container = map.getContainer().parentElement
    if (!container) return
    if (!document.fullscreenElement) {
      await container.requestFullscreen()
      setFullscreen(true)
    } else {
      await document.exitFullscreen()
      setFullscreen(false)
    }
    window.setTimeout(() => map.invalidateSize(), 150)
  }

  return (
    <button type="button" className="map-action map-fullscreen" onClick={() => void toggleFullscreen()} aria-label={fullscreen ? 'Exit fullscreen map' : 'Fullscreen map'}>
      <Expand size={17} aria-hidden="true" />
    </button>
  )
}

function HomeButton(): React.JSX.Element {
  const map = useMap()
  return (
    <button type="button" className="map-action map-home" onClick={() => map.fitBounds(GUWAHATI_BOUNDS, { padding: [16, 16] })} aria-label="Return to Guwahati extent">
      <Home size={17} aria-hidden="true" />
    </button>
  )
}

function MapView({
  layers,
  baseMap,
  hazardMode,
  compareHazards,
  drawSignal,
  resetSignal,
  searchTarget,
  onGeometryDrawn,
  onAnalyzeZone,
}: MapViewProps): React.JSX.Element {
  const geoJsonRef = useRef<LeafletGeoJSON | null>(null)
  const activeHazard = layers.combined ? 'combined' : layers.landslide ? 'landslide' : hazardMode

  const riskStyle = useMemo<StyleFunction>(() => {
    return (feature): PathOptions => {
      if (!feature) return {}
      const properties = (feature as RiskZoneFeature).properties
      const value = activeHazard === 'flood'
        ? properties.floodRisk
        : activeHazard === 'landslide'
          ? properties.landslideRisk
          : Math.round((properties.floodRisk + properties.landslideRisk) / 2)
      return {
        color: riskColor(value),
        fillColor: riskColor(value),
        fillOpacity: baseMap === 'satellite' ? 0.48 : 0.35,
        weight: 1.5,
      }
    }
  }, [activeHazard, baseMap])

  useEffect(() => {
    geoJsonRef.current?.setStyle(riskStyle)
  }, [riskStyle])

  const showRiskZones = layers.flood || layers.landslide || layers.combined
  const terrainColors = ['#416d57', '#6e8b58', '#a0985c', '#9c7656', '#765f52', '#584d4c', '#786656']
  const rainfallColors = ['#b7d8de', '#8bc1cd', '#60aabd', '#398da7', '#186b8d', '#124e70', '#2e7896']

  return (
    <main className="map-shell" aria-label="Interactive Guwahati hazard map">
      <MapContainer
        center={GUWAHATI_CENTER}
        zoom={12}
        minZoom={10}
        maxZoom={18}
        maxBounds={[[25.75, 91.25], [26.5, 92.3]]}
        zoomControl={false}
        className="map-container"
      >
        <TileLayer
          key={baseMap}
          url={baseMap === 'standard' ? STANDARD_TILES : SATELLITE_TILES}
          attribution={baseMap === 'standard' ? '&copy; OpenStreetMap contributors' : 'Tiles &copy; Esri'}
        />
        {layers.roads && <TileLayer url={STANDARD_TILES} opacity={baseMap === 'satellite' ? 0.44 : 0.18} attribution="Road reference &copy; OpenStreetMap contributors" />}

        {showRiskZones && (
          <GeoJSON
            ref={geoJsonRef}
            key={`risk-${activeHazard}`}
            data={riskZones}
            style={riskStyle}
            onEachFeature={(feature, layer) => {
              const zone = feature as RiskZoneFeature
              const floodLevel = riskLevel(zone.properties.floodRisk)
              const landslideLevel = riskLevel(zone.properties.landslideRisk)
              layer.bindPopup(`
                <div class="risk-popup">
                  <span class="popup-kicker">Illustrative risk zone</span>
                  <h3>${zone.properties.name}</h3>
                  <div class="popup-risk-grid">
                    <div><small>Flood risk</small><strong>${zone.properties.floodRisk}%</strong><span>${floodLevel}</span></div>
                    <div><small>Landslide</small><strong>${zone.properties.landslideRisk}%</strong><span>${landslideLevel}</span></div>
                  </div>
                  <dl>
                    <div><dt>Elevation</dt><dd>${zone.properties.elevation} m</dd></div>
                    <div><dt>River distance</dt><dd>${zone.properties.riverDistance} km</dd></div>
                    <div><dt>Demo events</dt><dd>${zone.properties.historicalEvents}</dd></div>
                  </dl>
                  <button class="popup-analyze" data-zone="${zone.properties.id}">Analyze area</button>
                </div>
              `)
              layer.on('popupopen', () => {
                const button = document.querySelector(`[data-zone="${zone.properties.id}"]`)
                button?.addEventListener('click', () => onAnalyzeZone(zone), { once: true })
              })
              layer.on({
                mouseover: () => (layer as L.Path).setStyle({ weight: 3, fillOpacity: 0.5 }),
                mouseout: () => geoJsonRef.current?.resetStyle(layer),
              })
            }}
          />
        )}

        {layers.rivers && (
          <GeoJSON
            data={brahmaputraRiver}
            style={{ color: '#237c9d', weight: 7, opacity: 0.82 }}
            onEachFeature={(feature, layer) => layer.bindTooltip(`${feature.properties?.name} · simplified OSM-aligned reference`, { sticky: true })}
          />
        )}
        {layers.waterBodies && (
          <GeoJSON
            data={waterBodies}
            style={{ color: '#2b88a7', weight: 1.5, fillColor: '#55a9c2', fillOpacity: 0.44 }}
            onEachFeature={(feature, layer) => layer.bindTooltip(`${feature.properties?.name} · illustrative simplified extent`, { sticky: true })}
          />
        )}

        {layers.elevation && riskZones.features.map((zone, index) => (
          <GeoJSON key={`elevation-${zone.properties.id}`} data={zone} style={{ color: terrainColors[index], fillColor: terrainColors[index], fillOpacity: 0.45, weight: 0.8 }}>
            <Tooltip sticky>{zone.properties.elevation} m · illustrative elevation</Tooltip>
          </GeoJSON>
        ))}
        {layers.slope && riskZones.features.map((zone, index) => {
          const slope = 3 + index * 3.2
          return (
            <GeoJSON key={`slope-${zone.properties.id}`} data={zone} style={{ color: '#72543d', fillColor: slope > 15 ? '#7c5140' : slope > 8 ? '#ad7c4d' : '#d5b979', fillOpacity: 0.44, weight: 0.8 }}>
              <Tooltip sticky>{slope.toFixed(1)}° · illustrative slope</Tooltip>
            </GeoJSON>
          )
        })}
        {layers.rainfall && riskZones.features.map((zone, index) => (
          <GeoJSON key={`rain-${zone.properties.id}`} data={zone} style={{ color: rainfallColors[index], fillColor: rainfallColors[index], fillOpacity: 0.5, weight: 0.8 }}>
            <Tooltip sticky>{70 + index * 21} mm / 24h · simulated rainfall</Tooltip>
          </GeoJSON>
        ))}

        {layers.buildings && riskZones.features.slice(1, 6).map((zone) => (
          <GeoJSON key={`built-${zone.properties.id}`} data={zone} style={{ color: '#59646e', fillColor: '#68747c', fillOpacity: 0.2, weight: 0.7 }}>
            <Tooltip sticky>Demo built-up concentration</Tooltip>
          </GeoJSON>
        ))}

        {layers.population && riskZones.features.map((zone, index) => {
          const coordinates = zone.geometry.coordinates[0]
          const longitude = coordinates.reduce((sum, coordinate) => sum + coordinate[0], 0) / coordinates.length
          const latitude = coordinates.reduce((sum, coordinate) => sum + coordinate[1], 0) / coordinates.length
          return (
            <Circle key={`population-${zone.properties.id}`} center={[latitude, longitude]} radius={600 + index * 140} pathOptions={{ color: '#725a8e', fillColor: '#8a71a4', fillOpacity: 0.27, weight: 1 }}>
              <Tooltip>{(11000 + index * 3700).toLocaleString()} demo population exposure</Tooltip>
            </Circle>
          )
        })}

        {infrastructure.features.map((feature) => {
          const [longitude, latitude] = feature.geometry.coordinates
          const visible = feature.properties.kind === 'hospital'
            ? layers.hospitals || layers.criticalInfrastructure
            : feature.properties.kind === 'school'
              ? layers.schools || layers.criticalInfrastructure
              : layers.bridges
          if (!visible) return null
          const color = feature.properties.kind === 'hospital' ? '#b33e4a' : feature.properties.kind === 'school' ? '#5969a8' : '#3a6f78'
          return (
            <CircleMarker key={feature.properties.name} center={[latitude, longitude]} radius={8} pathOptions={{ color: '#ffffff', weight: 2, fillColor: color, fillOpacity: 1 }}>
              <Tooltip direction="top">{feature.properties.name}</Tooltip>
              <Popup>
                <div className="asset-popup">
                  {feature.properties.kind === 'hospital' ? <Hospital size={16} /> : <School size={16} />}
                  <strong>{feature.properties.name}</strong>
                  <span>Reference location · verify before operational use</span>
                </div>
              </Popup>
            </CircleMarker>
          )
        })}

        {compareHazards && (
          <Polygon positions={[[26.099, 91.704], [26.119, 91.736], [26.103, 91.767], [26.083, 91.744]]} pathOptions={{ color: '#81649a', fillColor: '#81649a', fillOpacity: 0.26, dashArray: '6 5' }}>
            <Tooltip sticky>Flood 82% · Landslide 31% · demo comparison</Tooltip>
          </Polygon>
        )}

        <ZoomControl position="bottomright" />
        <ScaleControl position="bottomleft" imperial={false} />
        <MapController drawSignal={drawSignal} resetSignal={resetSignal} searchTarget={searchTarget} onGeometryDrawn={onGeometryDrawn} />
        <FullscreenButton />
        <HomeButton />
      </MapContainer>

      <div className="map-context-chip">
        <Crosshair size={14} aria-hidden="true" />
        Guwahati Metropolitan Area
      </div>
      <div className="demo-map-badge">DEMO OVERLAYS</div>
      <div className="map-legend" aria-label="Risk legend">
        <div>
          <span>Risk intensity</span>
          <small>Illustrative</small>
        </div>
        <ul>
          <li><i style={{ background: '#4d8b65' }} />Low</li>
          <li><i style={{ background: '#d4a72c' }} />Moderate</li>
          <li><i style={{ background: '#dd7246' }} />High</li>
          <li><i style={{ background: '#b83b3b' }} />Very high</li>
        </ul>
      </div>
    </main>
  )
}

export default MapView
