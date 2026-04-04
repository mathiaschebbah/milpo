import { useState, useEffect, useCallback } from 'react'
import { fetchNextPost, fetchProgress, fetchCategories, fetchVisualFormats, submitAnnotation } from '@/lib/api'

type Lookup = { id: number; name: string }

type Post = {
  ig_media_id: number
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
  const [visualFormats, setVisualFormats] = useState<Lookup[]>([])
  const [loading, setLoading] = useState(true)

  const loadNext = useCallback(async () => {
    setLoading(true)
    const data = await fetchNextPost()
    if (data.done) {
      setDone(true)
    } else {
      setCurrent(data)
    }
    const prog = await fetchProgress()
    setProgress(prog)
    setLoading(false)
  }, [])

  useEffect(() => {
    Promise.all([fetchCategories(), fetchVisualFormats()]).then(([cats, vfs]) => {
      setCategories(cats)
      setVisualFormats(vfs)
    })
    loadNext()
  }, [loadNext])

  const submit = async (categoryId: number, visualFormatId: number, strategy: 'Organic' | 'Brand Content') => {
    if (!current) return
    await submitAnnotation({
      ig_media_id: current.post.ig_media_id,
      category_id: categoryId,
      visual_format_id: visualFormatId,
      strategy,
    })
    await loadNext()
  }

  const skip = () => loadNext()

  return { current, done, progress, categories, visualFormats, loading, submit, skip }
}
