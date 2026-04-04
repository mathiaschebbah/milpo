import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { fetchTaxonomy, updateTaxonomyDescription, type TaxonomyItem } from '@/lib/api'

type Axis = 'visual-formats' | 'categories' | 'strategies'

const AXES: { key: Axis; label: string }[] = [
  { key: 'visual-formats', label: 'Formats visuels' },
  { key: 'categories', label: 'Catégories' },
  { key: 'strategies', label: 'Stratégies' },
]

type FormatGroup = 'post' | 'reel' | 'story'

const FORMAT_GROUPS: { key: FormatGroup; label: string; prefix: string }[] = [
  { key: 'post', label: 'Posts', prefix: 'post_' },
  { key: 'reel', label: 'Reels', prefix: 'reel_' },
  { key: 'story', label: 'Stories', prefix: 'story_' },
]

function stripPrefix(name: string): string {
  for (const g of FORMAT_GROUPS) {
    if (name.startsWith(g.prefix)) return name.slice(g.prefix.length)
  }
  return name
}


function InlineEdit({
  item,
  axis,
  onSaved,
}: {
  item: TaxonomyItem
  axis: Axis
  onSaved: (updated: TaxonomyItem) => void
}) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(item.description ?? '')
  const [saving, setSaving] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    setValue(item.description ?? '')
  }, [item.description])

  useEffect(() => {
    if (editing && textareaRef.current) {
      textareaRef.current.focus()
      textareaRef.current.setSelectionRange(value.length, value.length)
    }
  }, [editing])

  const save = useCallback(async () => {
    const trimmed = value.trim()
    const newDesc = trimmed || null
    if (newDesc === item.description) {
      setEditing(false)
      return
    }
    setSaving(true)
    try {
      const updated = await updateTaxonomyDescription(axis, item.id, newDesc)
      onSaved(updated)
    } finally {
      setSaving(false)
      setEditing(false)
    }
  }, [value, item, axis, onSaved])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      save()
    }
    if (e.key === 'Escape') {
      setValue(item.description ?? '')
      setEditing(false)
    }
  }

  if (editing) {
    return (
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={save}
        onKeyDown={handleKeyDown}
        disabled={saving}
        rows={3}
        className="w-full text-sm text-neutral-700 bg-white border border-neutral-300 rounded-lg px-3.5 py-2.5 resize-y focus:outline-none focus:ring-2 focus:ring-neutral-900 focus:border-transparent disabled:opacity-50"
        placeholder="Décris ce que l'on voit visuellement..."
      />
    )
  }

  return (
    <button
      onClick={() => setEditing(true)}
      className="w-full text-left rounded-lg border border-transparent hover:border-neutral-200 hover:bg-neutral-50/80 transition-colors"
    >
      {item.description ? (
        <p className="text-sm leading-relaxed text-neutral-600 whitespace-pre-line">{item.description}</p>
      ) : (
        <p className="text-sm text-neutral-300 italic">Ajouter une description...</p>
      )}
    </button>
  )
}


export function TaxonomyPage() {
  const [axis, setAxis] = useState<Axis>('visual-formats')
  const [formatGroup, setFormatGroup] = useState<FormatGroup>('post')
  const [items, setItems] = useState<TaxonomyItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    fetchTaxonomy(axis)
      .then(setItems)
      .finally(() => setLoading(false))
  }, [axis])

  const handleSaved = useCallback((updated: TaxonomyItem) => {
    setItems((prev) => prev.map((it) => (it.id === updated.id ? updated : it)))
  }, [])

  const filled = items.filter((it) => it.description).length

  const visibleItems = useMemo(() => {
    if (axis !== 'visual-formats') return items
    const prefix = FORMAT_GROUPS.find((g) => g.key === formatGroup)?.prefix ?? ''
    return items.filter((it) => it.name.startsWith(prefix))
  }, [items, axis, formatGroup])

  const groupCounts = useMemo(() => {
    if (axis !== 'visual-formats') return null
    return FORMAT_GROUPS.map((g) => {
      const groupItems = items.filter((it) => it.name.startsWith(g.prefix))
      return {
        ...g,
        total: groupItems.length,
        filled: groupItems.filter((it) => it.description).length,
      }
    })
  }, [items, axis])

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div className="flex p-0.5 bg-neutral-100 rounded-md">
          {AXES.map((a) => (
            <button
              key={a.key}
              onClick={() => setAxis(a.key)}
              className={`px-3 py-1.5 text-xs font-medium rounded transition-all ${
                axis === a.key
                  ? 'bg-white text-neutral-900 shadow-sm'
                  : 'text-neutral-500 hover:text-neutral-700'
              }`}
            >
              {a.label}
            </button>
          ))}
        </div>

        <Badge variant="outline" className="text-xs tabular-nums">
          {filled} / {items.length} décrites
        </Badge>
      </div>

      {axis === 'visual-formats' && groupCounts && (
        <div className="flex items-center gap-1 border-b border-neutral-200">
          {groupCounts.map((g) => (
            <button
              key={g.key}
              onClick={() => setFormatGroup(g.key)}
              className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors ${
                formatGroup === g.key
                  ? 'border-neutral-900 text-neutral-900'
                  : 'border-transparent text-neutral-400 hover:text-neutral-600'
              }`}
            >
              {g.label}
              <span className="ml-1.5 text-xs tabular-nums text-neutral-400">
                {g.filled}/{g.total}
              </span>
            </button>
          ))}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-24">
          <p className="text-sm text-neutral-400 animate-pulse">Chargement...</p>
        </div>
      ) : (
        <div className="divide-y divide-neutral-100 border border-neutral-200 rounded-lg bg-white">
          {visibleItems.map((item) => (
            <div
              key={item.id}
              className="grid grid-cols-[220px_1fr] items-start gap-6 px-5 py-4"
            >
              <div className="flex items-center gap-2 min-w-0 pt-0.5">
                {!item.description && (
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
                )}
                <code className="text-sm font-medium text-neutral-900">
                  {axis === 'visual-formats' ? stripPrefix(item.name) : item.name}
                </code>
              </div>
              <InlineEdit item={item} axis={axis} onSaved={handleSaved} />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
