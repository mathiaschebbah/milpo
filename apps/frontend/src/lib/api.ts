const API_BASE = '/v1'

type Lookup = {
  id: number
  name: string
}

type Progress = {
  total: number
  annotated: number
}

type NextPostResponse = {
  done?: boolean
  message?: string
  post: {
    ig_media_id: string
    shortcode: string | null
    caption: string | null
    timestamp: string
    media_type: string
    media_product_type: string
  }
  heuristic: {
    category_id: number | null
    heuristic_category: string | null
    visual_format_id: number | null
    heuristic_visual_format: string | null
    heuristic_strategy: string | null
    heuristic_subcategory: string | null
  }
  media: Array<{
    media_url: string | null
    thumbnail_url: string | null
    media_type: string
    media_order: number
    width: number | null
    height: number | null
  }>
}

type PostGridResponse = {
  items: Array<{
    ig_media_id: string
    shortcode: string | null
    media_type: string
    media_product_type: string
    thumbnail_url: string | null
    category: string | null
    visual_format: string | null
    strategy: string | null
    annotation_category: string | null
    annotation_visual_format: string | null
    annotation_strategy: string | null
    is_annotated: boolean
  }>
  total: number
  offset: number
  limit: number
}

type AnnotationResponse = {
  id: number
  ig_media_id: string
  category_id: number
  visual_format_id: number
  strategy: 'Organic' | 'Brand Content'
  annotator: string
  created_at: string
}

function getErrorMessage(text: string) {
  if (!text) return 'Empty error response'
  try {
    const payload = JSON.parse(text)
    if (payload && typeof payload === 'object') {
      if ('error' in payload && typeof payload.error === 'string') return payload.error
      if ('message' in payload && typeof payload.message === 'string') return payload.message
    }
  } catch {
    // Keep raw text when the server did not send JSON.
  }
  return text
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init)
  const text = await res.text()

  if (!res.ok) {
    throw new Error(`${res.status} ${getErrorMessage(text)}`)
  }

  if (!text) {
    throw new Error(`Empty JSON response for ${path}`)
  }

  try {
    return JSON.parse(text) as T
  } catch {
    throw new Error(`Invalid JSON response for ${path}: ${text.slice(0, 200)}`)
  }
}

export async function fetchNextPost(annotator = 'mathias', excludeIds: string[] = []): Promise<NextPostResponse> {
  const qs = new URLSearchParams({ annotator })
  excludeIds.forEach(excludeId => qs.append('exclude', excludeId))
  return requestJson<NextPostResponse>(`/posts/next?${qs}`)
}

export async function fetchProgress(annotator = 'mathias'): Promise<Progress> {
  return requestJson<Progress>(`/posts/progress?annotator=${annotator}`)
}

export async function fetchCategories(): Promise<Lookup[]> {
  return requestJson<Lookup[]>('/posts/categories')
}

export async function fetchVisualFormats(): Promise<Lookup[]> {
  return requestJson<Lookup[]>('/posts/visual-formats')
}

export async function fetchPostGrid(params: {
  offset?: number
  limit?: number
  status?: string
  category?: string
  annotator?: string
} = {}): Promise<PostGridResponse> {
  const qs = new URLSearchParams()
  if (params.offset) qs.set('offset', String(params.offset))
  if (params.limit) qs.set('limit', String(params.limit))
  if (params.status) qs.set('status', params.status)
  if (params.category) qs.set('category', params.category)
  qs.set('annotator', params.annotator ?? 'mathias')
  return requestJson<PostGridResponse>(`/posts/?${qs}`)
}

// --- Taxonomy ---

export type TaxonomyItem = {
  id: number
  name: string
  description: string | null
}

export async function fetchTaxonomy(axis: 'visual-formats' | 'categories' | 'strategies'): Promise<TaxonomyItem[]> {
  return requestJson<TaxonomyItem[]>(`/taxonomy/${axis}`)
}

export async function updateTaxonomyDescription(
  axis: 'visual-formats' | 'categories' | 'strategies',
  itemId: number,
  description: string | null,
): Promise<TaxonomyItem> {
  return requestJson<TaxonomyItem>(`/taxonomy/${axis}/${itemId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ description }),
  })
}

export async function submitAnnotation(data: {
  ig_media_id: string
  category_id: number
  visual_format_id: number
  strategy: 'Organic' | 'Brand Content'
}, annotator = 'mathias'): Promise<AnnotationResponse> {
  console.log('[API] submitAnnotation', data)
  try {
    return await requestJson<AnnotationResponse>(`/annotations/?annotator=${annotator}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
  } catch (error) {
    console.error('[API] submitAnnotation error', error)
    throw error
  }
}
