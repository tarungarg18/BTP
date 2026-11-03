import {
  CircleMarker,
  GeoJSON,
  MapContainer,
  ScaleControl,
  TileLayer,
  Tooltip,
  ZoomControl,
  useMap,
} from 'react-leaflet'
import type { Feature, FeatureCollection, GeoJsonObject } from 'geojson'
import L from 'leaflet'
import { useEffect, useMemo, useRef } from 'react'
import 'leaflet/dist/leaflet.css'

interface Endpoints {
  upstream: { name: string; lon: number; lat: number }
  downstream: { name: string; lon: number; lat: number }
}

interface MapWorkspaceProps {
  envelopeA?: GeoJsonObject
  envelopeB?: GeoJsonObject
  leftA?: GeoJsonObject
  rightA?: GeoJsonObject
  leftB?: GeoJsonObject
  rightB?: GeoJsonObject
  centerline?: GeoJsonObject
  sections?: GeoJsonObject
  changes?: FeatureCollection
  polygons?: FeatureCollection
  endpoints?: Endpoints
  revision: string
  showEnvelopeA: boolean
  showEnvelopeB: boolean
  showBanksA: boolean
  showBanksB: boolean
  showCenterline: boolean
  showSections: boolean
  showChange: boolean
  onSection: (props: Record<string, unknown>) => void
}

function FitCorridor({ data }: { data?: GeoJsonObject }) {
  const map = useMap()
  const fitted = useRef(false)
  useEffect(() => {
    if (!data || fitted.current) return
    const layer = L.geoJSON(data as GeoJSON.GeoJsonObject)
    const bounds = layer.getBounds()
    if (bounds.isValid()) {
      map.fitBounds(bounds, { padding: [36, 36], maxZoom: 8 })
      fitted.current = true
    }
  }, [data, map])
  return null
}

function styleEnvelope(color: string, opacity: number) {
  return { color, weight: 1.5, fillColor: color, fillOpacity: opacity }
}

export default function MapWorkspace(props: MapWorkspaceProps): React.JSX.Element {
  const changePointStyle = useMemo(() => {
    return (feature?: Feature) => {
      const cls = String(feature?.properties?.left_class ?? 'stable')
      const color =
        cls === 'candidate_erosion' ? '#b5483e' : cls === 'candidate_accretion' ? '#3d7a62' : '#8a938e'
      return {
        radius: 5,
        color: '#fff',
        weight: 1,
        fillColor: color,
        fillOpacity: 0.95,
      }
    }
  }, [])

  return (
    <main className="map-shell" aria-label="Assam Brahmaputra corridor map">
      <MapContainer
        center={[26.7, 93.0]}
        zoom={7}
        minZoom={6}
        maxZoom={14}
        zoomControl={false}
        preferCanvas
        className="map-canvas"
      >
        <FitCorridor data={props.centerline ?? props.envelopeA} />
        <TileLayer
          attribution="&copy; OpenStreetMap"
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <TileLayer
          url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
          opacity={0.55}
          attribution="Tiles &copy; Esri"
        />
        {props.showEnvelopeA && props.envelopeA && (
          <GeoJSON
            key={`envA-${props.revision}`}
            data={props.envelopeA}
            style={styleEnvelope('#176d8d', 0.28)}
          />
        )}
        {props.showEnvelopeB && props.envelopeB && (
          <GeoJSON
            key={`envB-${props.revision}`}
            data={props.envelopeB}
            style={styleEnvelope('#c56c48', 0.22)}
          />
        )}
        {props.showCenterline && props.centerline && (
          <GeoJSON
            key={`cl-${props.revision}`}
            data={props.centerline}
            style={{ color: '#e9a23b', weight: 3 }}
          />
        )}
        {props.showBanksA && props.leftA && (
          <GeoJSON key={`lA-${props.revision}`} data={props.leftA} style={{ color: '#2f6f8f', weight: 3 }} />
        )}
        {props.showBanksA && props.rightA && (
          <GeoJSON key={`rA-${props.revision}`} data={props.rightA} style={{ color: '#1f4f66', weight: 3 }} />
        )}
        {props.showBanksB && props.leftB && (
          <GeoJSON
            key={`lB-${props.revision}`}
            data={props.leftB}
            style={{ color: '#c56c48', weight: 3, dashArray: '6 4' }}
          />
        )}
        {props.showBanksB && props.rightB && (
          <GeoJSON
            key={`rB-${props.revision}`}
            data={props.rightB}
            style={{ color: '#9a4b32', weight: 3, dashArray: '6 4' }}
          />
        )}
        {props.showChange && props.polygons && (
          <GeoJSON
            key={`poly-${props.revision}`}
            data={props.polygons}
            style={(feature) => {
              const cls = String(feature?.properties?.class)
              if (cls === 'candidate_corridor_expansion') {
                return { color: '#b5483e', fillColor: '#b5483e', fillOpacity: 0.32, weight: 0.5 }
              }
              if (cls === 'candidate_corridor_contraction') {
                return { color: '#3d7a62', fillColor: '#3d7a62', fillOpacity: 0.32, weight: 0.5 }
              }
              return { color: '#88938e', fillOpacity: 0.04, weight: 0 }
            }}
          />
        )}
        {props.showChange && props.changes && (
          <GeoJSON
            key={`chg-${props.revision}`}
            data={props.changes}
            pointToLayer={(feature, latlng) => L.circleMarker(latlng, changePointStyle(feature))}
            onEachFeature={(feature, layer) => {
              layer.on('click', () => props.onSection(feature.properties ?? {}))
            }}
          />
        )}
        {props.showSections && props.sections && (
          <GeoJSON
            key={`xs-${props.revision}`}
            data={props.sections}
            style={{ color: '#31413b', weight: 1, opacity: 0.45 }}
            onEachFeature={(feature, layer) => {
              layer.on('click', () => props.onSection(feature.properties ?? {}))
            }}
          />
        )}
        {props.endpoints && (
          <>
            <CircleMarker
              center={[props.endpoints.upstream.lat, props.endpoints.upstream.lon]}
              radius={8}
              pathOptions={{ color: '#fff', weight: 2, fillColor: '#0d6662', fillOpacity: 1 }}
            >
              <Tooltip permanent direction="right" offset={[10, 0]} className="endpoint-label">
                {props.endpoints.upstream.name} · upstream
              </Tooltip>
            </CircleMarker>
            <CircleMarker
              center={[props.endpoints.downstream.lat, props.endpoints.downstream.lon]}
              radius={8}
              pathOptions={{ color: '#fff', weight: 2, fillColor: '#c56c48', fillOpacity: 1 }}
            >
              <Tooltip permanent direction="top" offset={[0, -8]} className="endpoint-label">
                {props.endpoints.downstream.name} · downstream
              </Tooltip>
            </CircleMarker>
          </>
        )}
        <ZoomControl position="bottomright" />
        <ScaleControl position="bottomleft" imperial={false} />
      </MapContainer>
      <div className="map-legend">
        <strong>Assam main stem</strong>
        <span><i className="swatch gold" /> Reference centerline</span>
        <span><i className="swatch teal" /> Envelope / banks A</span>
        <span><i className="swatch rust" /> Envelope / banks B</span>
        <span><i className="dot red" /> Candidate erosion</span>
        <span><i className="dot green" /> Candidate accretion</span>
        <em>Click a red point or a 300 m section to inspect.</em>
      </div>
    </main>
  )
}
