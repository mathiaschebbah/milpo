import { useCallback, useEffect, useRef, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { fetchTaxonomy, updateTaxonomyDescription, type TaxonomyItem } from '@/lib/api'

type Axis = 'visual-formats' | 'categories' | 'strategies'

const AXES: { key: Axis; label: string }[] = [
  { key: 'visual-formats', label: 'Formats visuels' },
  { key: 'categories', label: 'Catégories' },
  { key: 'strategies', label: 'Stratégies' },
]

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
        rows={2}
        className="w-full text-sm text-neutral-700 bg-white border border-neutral-300 rounded-md px-3 py-2 resize-none focus:outline-none focus:ring-2 focus:ring-neutral-900 focus:border-transparent disabled:opacity-50"
        placeholder="Décris ce que l'on voit visuellement..."
      />
    )
  }

  return (
    <button
      onClick={() => setEditing(true)}
      className="w-full text-left px-3 py-2 rounded-md border border-transparent hover:border-neutral-200 hover:bg-neutral-50 transition-colors group"
    >
      {item.description ? (
        <p className="text-sm text-neutral-600 whitespace-pre-line">{item.description}</p>
      ) : (
        <p className="text-sm text-neutral-400 italic">Clic pour ajouter une description...</p>
      )}
    </button>
  )
}

export function TaxonomyPage() {
  const [axis, setAxis] = useState<Axis>('visual-formats')
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

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex p-0.5 bg-neutral-100 rounded-md">
          {AXES.map((a) => (
            <button
              key={a.key}
              onClick={() => setAxis(a.key)}
              className={`px-2.5 py-1 text-xs font-medium rounded transition-all ${
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

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <p className="text-sm text-neutral-400 animate-pulse">Chargement...</p>
        </div>
      ) : (
        <div className="border border-neutral-200 rounded-lg bg-white divide-y divide-neutral-100">
          {items.map((item) => (
            <div key={item.id} className="grid grid-cols-[200px_1fr] items-start">
              <div className="px-4 py-3 border-r border-neutral-100">
                <span className="text-sm font-medium text-neutral-900">{item.name}</span>
              </div>
              <div className="px-2 py-1">
                <InlineEdit item={item} axis={axis} onSaved={handleSaved} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
