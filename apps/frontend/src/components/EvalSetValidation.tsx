import { useState, useEffect, useMemo } from 'react'
import { useUrlState } from '@/hooks/useUrlState'
import { fetchEvalSetStats, fetchPostGrid, type EvalSetStat } from '@/lib/api'
import { Badge } from '@/components/ui/badge'

type GridItem = {
  ig_media_id: string
  shortcode: string | null
  caption: string | null
  timestamp: string | null
  media_type: string
  media_product_type: string
  thumbnail_url: string | null
  annotation_visual_format: string | null
  annotation_category: string | null
  annotation_strategy: string | null
  annotation_doubtful: boolean
  is_annotated: boolean
}

type Props = {
  setName: string
  onOpenPost: (igMediaId: string) => void
}

export function EvalSetValidation({ setName, onOpenPost }: Props) {
  const [stats, setStats] = useState<EvalSetStat[]>([])
  const [scope, setScope] = useUrlState<'FEED' | 'REELS'>('ev_scope', 'FEED', {
    serialize: (v) => v,
    deserialize: (raw) => (raw === 'REELS' ? 'REELS' : 'FEED'),
  })
  const [selectedFormat, setSelectedFormat] = useUrlState<string>('ev_format', '', {
    serialize: (v) => v,
    deserialize: (raw) => raw,
  })
  const [items, setItems] = useState<GridItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchEvalSetStats(setName).then(setStats)
  }, [setName])

  const feedFormats = useMemo(
    () => stats.filter((s) => s.scope === 'FEED').sort((a, b) => a.format_name.localeCompare(b.format_name)),
    [stats],
  )
  const reelsFormats = useMemo(
    () => stats.filter((s) => s.scope === 'REELS').sort((a, b) => a.format_name.localeCompare(b.format_name)),
    [stats],
  )

  const currentFormats = scope === 'FEED' ? feedFormats : reelsFormats

  const totalByScope = useMemo(() => ({
    FEED: feedFormats.reduce((s, f) => s + f.total, 0),
    REELS: reelsFormats.reduce((s, f) => s + f.total, 0),
  }), [feedFormats, reelsFormats])

  useEffect(() => {
    if (!selectedFormat) return
    setLoading(true)
    fetchPostGrid({
      eval_set: setName,
      visual_format: selectedFormat,
      limit: 50,
    }).then((data) => {
      setItems(data.items as unknown as GridItem[])
      setLoading(false)
    })
  }, [setName, selectedFormat])

  // Auto-select first format when switching scope
  useEffect(() => {
    if (currentFormats.length > 0 && !currentFormats.find((f) => f.format_name === selectedFormat)) {
      setSelectedFormat(currentFormats[0].format_name)
    }
  }, [scope, currentFormats, selectedFormat, setSelectedFormat])

  const selectedStat = currentFormats.find((f) => f.format_name === selectedFormat)

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-semibold text-neutral-900">
            Set {setName}
          </h2>
          <Badge variant="outline" className="text-[11px]">
            {totalByScope.FEED + totalByScope.REELS} posts
          </Badge>
        </div>
      </div>

      {/* Scope tabs */}
      <div className="flex gap-1 p-1 bg-neutral-100 rounded-lg w-fit">
        <button
          onClick={() => setScope('FEED')}
          className={`px-4 py-1.5 text-xs font-medium rounded-md transition-all ${
            scope === 'FEED'
              ? 'bg-white text-neutral-900 shadow-sm'
              : 'text-neutral-500 hover:text-neutral-700'
          }`}
        >
          FEED ({totalByScope.FEED})
        </button>
        <button
          onClick={() => setScope('REELS')}
          className={`px-4 py-1.5 text-xs font-medium rounded-md transition-all ${
            scope === 'REELS'
              ? 'bg-white text-neutral-900 shadow-sm'
              : 'text-neutral-500 hover:text-neutral-700'
          }`}
        >
          REELS ({totalByScope.REELS})
        </button>
      </div>

      {/* Format buttons */}
      <div className="flex flex-wrap gap-1.5">
        {currentFormats.map((f) => {
          const isActive = f.format_name === selectedFormat
          const label = f.format_name.replace(/^(post_|reel_)/, '')
          return (
            <button
              key={f.format_name}
              onClick={() => setSelectedFormat(f.format_name)}
              className={`px-2.5 py-1.5 text-xs font-medium rounded-md border transition-all ${
                isActive
                  ? 'bg-neutral-900 text-white border-neutral-900'
                  : 'bg-white text-neutral-600 border-neutral-200 hover:border-neutral-400'
              }`}
            >
              {label}
              <span className={`ml-1.5 tabular-nums ${isActive ? 'text-neutral-400' : 'text-neutral-400'}`}>
                {f.total}
              </span>
            </button>
          )
        })}
      </div>

      {/* Selected format info */}
      {selectedStat && (
        <div className="flex items-center gap-2 text-xs text-neutral-500">
          <span className="font-medium text-neutral-700">{selectedFormat}</span>
          <span>&middot;</span>
          <span>{selectedStat.total} posts</span>
        </div>
      )}

      {/* Grid */}
      {loading && selectedFormat ? (
        <div className="flex items-center justify-center py-16">
          <p className="text-sm text-neutral-400 animate-pulse">Chargement...</p>
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
          {items.map((item) => (
            <button
              key={item.ig_media_id}
              onClick={() => onOpenPost(item.ig_media_id)}
              className="group relative bg-white rounded-lg border border-neutral-200 overflow-hidden hover:border-neutral-400 transition-all text-left"
            >
              <div className="aspect-square bg-neutral-100">
                {item.thumbnail_url ? (
                  <img
                    src={item.thumbnail_url}
                    alt=""
                    className="w-full h-full object-cover"
                    loading="lazy"
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center text-neutral-300 text-xs">
                    Pas de media
                  </div>
                )}
              </div>

              {/* Annotation status */}
              <div className="absolute top-1.5 right-1.5">
                {item.is_annotated && !item.annotation_doubtful && (
                  <div className="w-5 h-5 rounded-full bg-emerald-500 text-white flex items-center justify-center text-[10px]">
                    &#10003;
                  </div>
                )}
                {item.annotation_doubtful && (
                  <div className="w-5 h-5 rounded-full bg-amber-500 text-white flex items-center justify-center text-[10px] font-bold">
                    ?
                  </div>
                )}
              </div>

              {/* Caption on hover */}
              <div className="absolute inset-0 bg-black/70 opacity-0 group-hover:opacity-100 transition-opacity p-2 flex items-end">
                <p className="text-[10px] text-white line-clamp-4 leading-relaxed">
                  {item.caption || 'Pas de caption'}
                </p>
              </div>

              {/* Footer */}
              <div className="p-1.5 border-t border-neutral-100">
                <div className="flex flex-wrap gap-0.5">
                  {item.annotation_visual_format && (
                    <span className="text-[9px] px-1 py-0.5 rounded bg-neutral-100 text-neutral-600 truncate max-w-full">
                      {item.annotation_visual_format.replace(/^(post_|reel_)/, '')}
                    </span>
                  )}
                  {item.annotation_category && (
                    <span className="text-[9px] px-1 py-0.5 rounded bg-blue-50 text-blue-600 truncate max-w-full">
                      {item.annotation_category}
                    </span>
                  )}
                </div>
              </div>
            </button>
          ))}
        </div>
      )}

      {!loading && items.length === 0 && selectedFormat && (
        <div className="flex items-center justify-center py-16">
          <p className="text-sm text-neutral-400">Aucun post pour ce format</p>
        </div>
      )}
    </div>
  )
}
