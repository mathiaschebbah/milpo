import { useState, useEffect, useCallback } from 'react'
import { fetchNextPost, fetchPost, fetchProgress, fetchCategories, fetchTaxonomy, submitAnnotation, type TaxonomyItem } from '@/lib/api'

type Lookup = { id: number; name: string }

type Post = {
  ig_media_id: string
  shortcode: string | null
  caption: string | null
  timestamp: string
  media_type: string
  media_product_type: string
}

type Heuristic = {
  category_id: number | null
  heuristic_category: string | null
  visual_format_id: number | null
  heuristic_visual_format: string | null
  heuristic_strategy: string | null
  heuristic_subcategory: string | null
}

type Media = {
  media_url: string | null
  thumbnail_url: string | null
  media_type: string
  media_order: number
  width: number | null
  height: number | null
}

type Annotation = {
  category_id: number | null
  visual_format_id: number | null
  strategy: string | null
}

export type PostData = {
  post: Post & { split?: string | null }
  heuristic: Heuristic
  media: Media[]
  annotation?: Annotation | null
}

export function useAnnotation() {
  const [current, setCurrent] = useState<PostData | null>(null)
  const [done, setDone] = useState(false)
  const [progress, setProgress] = useState({ total: 0, annotated: 0 })
  const [categories, setCategories] = useState<Lookup[]>([])
  const [visualFormats, setVisualFormats] = useState<TaxonomyItem[]>([])
  const [skippedIds, setSkippedIds] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [ready, setReady] = useState(false)
  const [mode, setMode] = useState<'next' | 'doubtful'>('next')

  const loadNext = useCallback(async (excludeIds: string[] = []) => {
    setLoading(true)
    try {
      let activeExcludes = excludeIds
      let [data, prog] = await Promise.all([fetchNextPost('mathias', activeExcludes, mode), fetchProgress()])

      // If every remaining post was skipped, restart from the skipped pool.
      if (data.done && activeExcludes.length > 0) {
        activeExcludes = []
        setSkippedIds([])
        ;[data, prog] = await Promise.all([fetchNextPost('mathias', [], mode), fetchProgress()])
      }

      if (data.done) {
        setDone(true)
        setCurrent(null)
      } else {
        setDone(false)
        setCurrent(data)
      }
      setProgress(prog)
    } finally {
      setLoading(false)
    }
  }, [mode])

  // Charger les lookups d'abord, puis le premier post
  useEffect(() => {
    Promise.all([fetchCategories(), fetchTaxonomy('visual-formats')]).then(([cats, vfs]) => {
      setCategories(cats)
      setVisualFormats(vfs)
      setReady(true)
    })
  }, [])

  useEffect(() => {
    if (ready) loadNext()
  }, [ready, loadNext])

  const submit = async (categoryId: number, visualFormatId: number, strategy: 'Organic' | 'Brand Content', doubtful = false) => {
    if (!current || submitting) return
    setSubmitting(true)
    try {
      const remainingSkippedIds = skippedIds.filter(id => id !== current.post.ig_media_id)
      await submitAnnotation({
        ig_media_id: current.post.ig_media_id,
        category_id: categoryId,
        visual_format_id: visualFormatId,
        strategy,
        doubtful,
      })
      setSkippedIds(remainingSkippedIds)
      await loadNext(remainingSkippedIds)
    } finally {
      setSubmitting(false)
    }
  }

  const skip = useCallback(async () => {
    if (!current) return
    const nextSkippedIds = [...new Set([...skippedIds, current.post.ig_media_id])]
    setSkippedIds(nextSkippedIds)
    await loadNext(nextSkippedIds)
  }, [current, skippedIds, loadNext])

  const loadPost = useCallback(async (igMediaId: string) => {
    setLoading(true)
    try {
      const [data, prog] = await Promise.all([fetchPost(igMediaId), fetchProgress()])
      setDone(false)
      setCurrent(data)
      setProgress(prog)
    } finally {
      setLoading(false)
    }
  }, [])

  const updateVisualFormat = useCallback((updated: TaxonomyItem) => {
    setVisualFormats(prev => prev.map(vf => vf.id === updated.id ? updated : vf))
  }, [])

  const switchMode = useCallback((newMode: 'next' | 'doubtful') => {
    setMode(newMode)
    setSkippedIds([])
    setDone(false)
  }, [])

  useEffect(() => {
    if (ready) { setSkippedIds([]); loadNext() }
  }, [mode])

  return { current, done, progress, categories, visualFormats, loading: loading || !ready, submitting, submit, skip, loadPost, updateVisualFormat, mode, switchMode }
}
