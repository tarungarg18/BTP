import type { ChangePoints, ChangeStats, IdentifyResult, PortalSummary, WaterMask } from './types'

export interface ComputeStatus {
  running: boolean
  step: string
  detail: string
  done: boolean
  error: string | null
  change: ChangeStats | null
  points: ChangePoints | null
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) {
    let detail = `${path} ${response.status}`
    try {
      const body = await response.json() as { detail?: string }
      if (typeof body.detail === 'string' && body.detail) detail = body.detail
    } catch {
      detail = `${path} ${response.status}`
    }
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

export const api = {
  summary: () => getJson<PortalSummary>('/api/summary'),
  masks: () => getJson<WaterMask[]>('/api/masks'),
  change: (laterId: string, earlierId?: string) => {
    const query = new URLSearchParams({ later: laterId })
    if (earlierId) query.set('earlier', earlierId)
    return getJson<ChangeStats>(`/api/change?${query.toString()}`)
  },
  points: (laterId: string, earlierId: string) =>
    getJson<ChangePoints>(`/api/points?later=${encodeURIComponent(laterId)}&earlier=${encodeURIComponent(earlierId)}`),
  periods: () => getJson<Array<{ id: string; label: string | null; water_display: string | null; scene_count: number | null; file: string | null; png: string }>>('/api/periods'),
  latest: () => getJson<{ end: string | null; source: string; optical: { when: string; date: string } | null; microwave: { when: string; date: string } | null }>('/api/latest'),
  compute: (laterId: string, earlierId: string) => {
    const query = new URLSearchParams({ later: laterId })
    if (earlierId) query.set('earlier', earlierId)
    return fetch(`/api/compute?${query.toString()}`, { method: 'POST' }).then(async (response) => {
      if (!response.ok) {
        let detail = 'Compute did not start'
        try {
          const body = await response.json() as { detail?: string }
          if (typeof body.detail === 'string' && body.detail) detail = body.detail
        } catch {
          detail = 'Compute did not start'
        }
        throw new Error(detail)
      }
      return response.json() as Promise<{ started: boolean }>
    })
  },
  computeStatus: () => getJson<ComputeStatus>('/api/compute'),
  identify: (lon: number, lat: number, laterId: string, earlierId: string) => {
    const query = new URLSearchParams({
      lon: String(lon),
      lat: String(lat),
      later: laterId,
      earlier: earlierId,
    })
    return getJson<IdentifyResult>(`/api/identify?${query.toString()}`)
  },
}
