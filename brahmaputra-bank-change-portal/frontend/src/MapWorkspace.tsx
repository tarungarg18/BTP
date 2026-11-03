import { GeoJSON, MapContainer, ScaleControl, TileLayer, ZoomControl } from 'react-leaflet'
import type { Feature, FeatureCollection, GeoJsonObject } from 'geojson'
import L from 'leaflet'
import { useMemo } from 'react'
import 'leaflet/dist/leaflet.css'

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
  showEnvelopeA: boolean
  showEnvelopeB: boolean
  showBanksA: boolean
  showBanksB: boolean
  showCenterline: boolean
  showSections: boolean
  showChange: boolean
  onSection: (props: Record<string, unknown>) => void
}

function styleEnvelope(color: string, opacity: number) {
  return { color, weight: 1, fillColor: color, fillOpacity: opacity }
}

export default function MapWorkspace(props: MapWorkspaceProps): React.JSX.Element {
  const changePointStyle = useMemo(() => {
    return (feature?: Feature) => {
      const cls = String(feature?.properties?.left_class ?? 'stable')
      const color =
        cls === 'candidate_erosion' ? '#b5483e' : cls === 'candidate_accretion' ? '#3d7a62' : '#8a938e'
      return {
        radius: 4,
        color: '#fff',
        weight: 1,
        fillColor: color,
        fillOpacity: 0.9,
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
        className="map-canvas"
      >
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
          <GeoJSON data={props.envelopeA} style={styleEnvelope('#176d8d', 0.18)} />
        )}
        {props.showEnvelopeB && props.envelopeB && (
          <GeoJSON data={props.envelopeB} style={styleEnvelope('#c56c48', 0.16)} />
        )}
        {props.showCenterline && props.centerline && (
          <GeoJSON data={props.centerline} style={{ color: '#e9a23b', weight: 2 }} />
        )}
        {props.showBanksA && props.leftA && (
          <GeoJSON data={props.leftA} style={{ color: '#2f6f8f', weight: 2 }} />
        )}
        {props.showBanksA && props.rightA && (
          <GeoJSON data={props.rightA} style={{ color: '#1f4f66', weight: 2 }} />
        )}
        {props.showBanksB && props.leftB && (
          <GeoJSON data={props.leftB} style={{ color: '#c56c48', weight: 2, dashArray: '5 4' }} />
        )}
        {props.showBanksB && props.rightB && (
          <GeoJSON data={props.rightB} style={{ color: '#9a4b32', weight: 2, dashArray: '5 4' }} />
        )}
        {props.showChange && props.polygons && (
          <GeoJSON
            data={props.polygons}
            style={(feature) => {
              const cls = String(feature?.properties?.class)
              if (cls === 'candidate_corridor_expansion') {
                return { color: '#b5483e', fillColor: '#b5483e', fillOpacity: 0.28, weight: 0.5 }
              }
              if (cls === 'candidate_corridor_contraction') {
                return { color: '#3d7a62', fillColor: '#3d7a62', fillOpacity: 0.28, weight: 0.5 }
              }
              return { color: '#88938e', fillOpacity: 0.04, weight: 0 }
            }}
          />
        )}
        {props.showChange && props.changes && (
          <GeoJSON
            data={props.changes}
            pointToLayer={(feature, latlng) => L.circleMarker(latlng, changePointStyle(feature))}
          />
        )}
        {props.showSections && props.sections && (
          <GeoJSON
            data={props.sections}
            style={{ color: '#31413b', weight: 1, opacity: 0.45 }}
            onEachFeature={(feature, layer) => {
              layer.on('click', () => props.onSection(feature.properties ?? {}))
            }}
          />
        )}
        <ZoomControl position="bottomright" />
        <ScaleControl position="bottomleft" imperial={false} />
      </MapContainer>
    </main>
  )
}
