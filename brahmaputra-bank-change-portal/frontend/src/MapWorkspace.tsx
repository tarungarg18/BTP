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
import type { FeatureCollection, GeoJsonObject } from 'geojson'
import L from 'leaflet'
import { useEffect } from 'react'
import 'leaflet/dist/leaflet.css'

interface Endpoints {
  upstream: { name: string; lon: number; lat: number }
  downstream: { name: string; lon: number; lat: number }
}

interface MapWorkspaceProps {
  waterA?: GeoJsonObject
  waterB?: GeoJsonObject
  leftA?: GeoJsonObject
  rightA?: GeoJsonObject
  leftB?: GeoJsonObject
  rightB?: GeoJsonObject
  centerline?: GeoJsonObject
  sections?: GeoJsonObject
  polygons?: FeatureCollection
  endpoints?: Endpoints
  revision: string
  showWaterA: boolean
  showWaterB: boolean
  showBanksA: boolean
  showBanksB: boolean
  showCenterline: boolean
  showSections: boolean
  showChange: boolean
  onSection: (props: Record<string, unknown>) => void
}

function FitRiver({ data, revision }: { data?: GeoJsonObject; revision: string }) {
  const map = useMap()
  useEffect(() => {
    if (!data) return
    const layer = L.geoJSON(data as GeoJSON.GeoJsonObject)
    const bounds = layer.getBounds()
    if (bounds.isValid()) {
      map.fitBounds(bounds, { padding: [28, 28], maxZoom: 11 })
    }
  }, [data, map, revision])
  return null
}

export default function MapWorkspace(props: MapWorkspaceProps): React.JSX.Element {
  return (
    <main className="map-shell" aria-label="Assam Brahmaputra satellite water map">
      <MapContainer
        center={[26.7, 93.0]}
        zoom={7}
        minZoom={6}
        maxZoom={15}
        zoomControl={false}
        preferCanvas
        className="map-canvas"
      >
        <FitRiver data={props.waterB ?? props.waterA ?? props.centerline} revision={props.revision} />
        <TileLayer
          url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
          attribution="Tiles &copy; Esri"
        />
        {props.showWaterA && props.waterA && (
          <GeoJSON
            key={`wA-${props.revision}`}
            data={props.waterA}
            style={{ color: '#0b4c70', weight: 0.8, fillColor: '#1d6fa3', fillOpacity: 0.38 }}
          />
        )}
        {props.showWaterB && props.waterB && (
          <GeoJSON
            key={`wB-${props.revision}`}
            data={props.waterB}
            style={{ color: '#c05621', weight: 1.6, fillColor: '#e07a3d', fillOpacity: 0.18 }}
          />
        )}
        {props.showCenterline && props.centerline && (
          <GeoJSON
            key={`cl-${props.revision}`}
            data={props.centerline}
            style={{ color: '#f2c14e', weight: 2.4 }}
          />
        )}
        {props.showBanksA && props.leftA && (
          <GeoJSON key={`lA-${props.revision}`} data={props.leftA} style={{ color: '#245e78', weight: 2 }} />
        )}
        {props.showBanksA && props.rightA && (
          <GeoJSON key={`rA-${props.revision}`} data={props.rightA} style={{ color: '#163e50', weight: 2 }} />
        )}
        {props.showBanksB && props.leftB && (
          <GeoJSON
            key={`lB-${props.revision}`}
            data={props.leftB}
            style={{ color: '#c05621', weight: 2.4, dashArray: '7 4' }}
          />
        )}
        {props.showBanksB && props.rightB && (
          <GeoJSON
            key={`rB-${props.revision}`}
            data={props.rightB}
            style={{ color: '#8a3a16', weight: 2.4, dashArray: '7 4' }}
          />
        )}
        {props.showChange && props.polygons && (
          <GeoJSON
            key={`poly-${props.revision}`}
            data={props.polygons}
            style={(feature) => {
              const cls = String(feature?.properties?.class)
              if (cls === 'candidate_corridor_expansion') {
                return { color: '#b5483e', fillColor: '#b5483e', fillOpacity: 0.45, weight: 0.6 }
              }
              if (cls === 'candidate_corridor_contraction') {
                return { color: '#2f7a5e', fillColor: '#2f7a5e', fillOpacity: 0.45, weight: 0.6 }
              }
              return { color: '#88938e', fillOpacity: 0, weight: 0 }
            }}
          />
        )}
        {props.showSections && props.sections && (
          <GeoJSON
            key={`xs-${props.revision}`}
            data={props.sections}
            style={{ color: '#f4f1ea', weight: 1, opacity: 0.7 }}
            onEachFeature={(feature, layer) => {
              layer.on('click', () => props.onSection(feature.properties ?? {}))
            }}
          />
        )}
        {props.endpoints && (
          <>
            <CircleMarker
              center={[props.endpoints.upstream.lat, props.endpoints.upstream.lon]}
              radius={7}
              pathOptions={{ color: '#fff', weight: 2, fillColor: '#0d6662', fillOpacity: 1 }}
            >
              <Tooltip permanent direction="right" offset={[10, 0]} className="endpoint-label">
                {props.endpoints.upstream.name}
              </Tooltip>
            </CircleMarker>
            <CircleMarker
              center={[props.endpoints.downstream.lat, props.endpoints.downstream.lon]}
              radius={7}
              pathOptions={{ color: '#fff', weight: 2, fillColor: '#c56c48', fillOpacity: 1 }}
            >
              <Tooltip permanent direction="top" offset={[0, -8]} className="endpoint-label">
                {props.endpoints.downstream.name}
              </Tooltip>
            </CircleMarker>
          </>
        )}
        <ZoomControl position="bottomright" />
        <ScaleControl position="bottomleft" imperial={false} />
      </MapContainer>
      <div className="map-legend">
        <strong>What the colours mean</strong>
        <span><i className="swatch teal" /> Water on the earlier date</span>
        <span><i className="swatch rust" /> Water on the later date</span>
        <span><i className="swatch gold" /> Middle of the channel</span>
        <span><i className="dot red" /> River got wider (candidate erosion)</span>
        <span><i className="dot green" /> River got narrower (candidate accretion)</span>
        <em>Zoom in. The blue fill should sit on the real Brahmaputra in the satellite photo — not as a straight tube across land.</em>
      </div>
    </main>
  )
}
