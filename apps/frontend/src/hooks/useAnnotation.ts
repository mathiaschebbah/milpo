import { useState, useEffect, useCallback } from 'react'
import { fetchNextPost, fetchProgress, fetchCategories, fetchTaxonomy, submitAnnotation, type TaxonomyItem } from '@/lib/api'

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

export type PostData = {
  post: Post
  heuristic: Heuristic
  media: Media[]
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

  const loadNext = useCallback(async (excludeIds: string[] = []) => {
    setLoading(true)
    try {
      let activeExcludes = excludeIds
      let [data, prog] = await Promise.all([fetchNextPost('mathias', activeExcludes), fetchProgress()])

      // If every remaining post was skipped, restart from the skipped pool.
      if (data.done && activeExcludes.length > 0) {
        activeExcludes = []
        setSkippedIds([])
        ;[data, prog] = await Promise.all([fetchNextPost(), fetchProgress()])
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
  }, [])

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

  const submit = async (categoryId: number, visualFormatId: number, strategy: 'Organic' | 'Brand Content') => {
    if (!current || submitting) return
    setSubmitting(true)
    try {
      const remainingSkippedIds = skippedIds.filter(id => id !== current.post.ig_media_id)
      await submitAnnotation({
        ig_media_id: current.post.ig_media_id,
        category_id: categoryId,
        visual_format_id: visualFormatId,
        strategy,
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

  const updateVisualFormat = useCallback((updated: TaxonomyItem) => {
    setVisualFormats(prev => prev.map(vf => vf.id === updated.id ? updated : vf))
  }, [])

  return { current, done, progress, categories, visualFormats, loading: loading || !ready, submitting, submit, skip, updateVisualFormat }
}
