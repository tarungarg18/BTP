import type { Acquisition, Comparison, EpochSummary, StudyArea } from './types'

const base = ''

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${base}${path}`)
  if (!response.ok) throw new Error(`${path} ${response.status}`)
  return response.json() as Promise<T>
}

export const api = {
  studyArea: () => getJson<StudyArea>('/api/study-area'),
  epochs: () => getJson<EpochSummary[]>('/api/epochs'),
  acquisitions: () => getJson<Acquisition[]>('/api/acquisitions'),
  epochLayers: (id: string) => getJson<Record<string, GeoJSON.GeoJsonObject>>(`/api/epochs/${id}/layers`),
  reference: () => getJson<{ centerline: GeoJSON.FeatureCollection; reaches: { reach_id: string }[] }>('/api/reference'),
  comparisons: () => getJson<Array<Pick<Comparison, 'id' | 'epoch_a' | 'epoch_b' | 'epoch_a_id' | 'epoch_b_id' | 'tolerance_m' | 'disclaimer'>>>('/api/comparisons'),
  comparison: (id: string) => getJson<Comparison>(`/api/comparisons/${id}`),
  createComparison: async (epochAId: string, epochBId: string): Promise<Comparison> => {
    const response = await fetch('/api/comparisons', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ epoch_a_id: epochAId, epoch_b_id: epochBId }),
    })
    if (!response.ok) throw new Error('comparison failed')
    return response.json() as Promise<Comparison>
  },
  jobs: () => getJson<Array<{ id: string; status: string; kind: string }>>('/api/jobs'),
}
