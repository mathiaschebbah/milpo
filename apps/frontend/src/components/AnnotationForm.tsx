import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger } from '@/components/ui/select'
import type { PostData } from '@/hooks/useAnnotation'
import { updateTaxonomyDescription, type TaxonomyItem } from '@/lib/api'

type Lookup = { id: number; name: string }

type Props = {
  data: PostData
  categories: Lookup[]
  visualFormats: TaxonomyItem[]
  onSubmit: (categoryId: number, visualFormatId: number, strategy: 'Organic' | 'Brand Content') => void
  onSkip: () => void
  onFormatUpdated?: (updated: TaxonomyItem) => void
}

function FormatDescription({
  item,
  onSaved,
}: {
  item: TaxonomyItem
  onSaved?: (updated: TaxonomyItem) => void
}) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(item.description ?? '')
  const [saving, setSaving] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    setValue(item.description ?? '')
    setEditing(false)
  }, [item.id, item.description])

  useEffect(() => {
    if (editing && textareaRef.current) {
      textareaRef.current.focus()
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
      const updated = await updateTaxonomyDescription('visual-formats', item.id, newDesc)
      onSaved?.(updated)
    } finally {
      setSaving(false)
      setEditing(false)
    }
  }, [value, item, onSaved])

  if (editing) {
    return (
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); save() }
          if (e.key === 'Escape') { setValue(item.description ?? ''); setEditing(false) }
        }}
        disabled={saving}
        rows={3}
        className="w-full text-xs text-neutral-600 bg-neutral-50 border border-neutral-200 rounded px-2.5 py-2 resize-y focus:outline-none focus:ring-1 focus:ring-neutral-400 disabled:opacity-50"
        placeholder="Décris ce que l'on voit visuellement..."
      />
    )
  }

  return (
    <button
      onClick={() => setEditing(true)}
      className="w-full text-left px-2.5 py-2 rounded bg-neutral-50 border border-neutral-100 hover:border-neutral-200 transition-colors"
    >
      {item.description ? (
        <p className="text-xs leading-relaxed text-neutral-500">{item.description}</p>
      ) : (
        <p className="text-xs text-neutral-300 italic">Ajouter une description...</p>
      )}
    </button>
  )
}

const FORMAT_PREFIX: Record<string, string> = {
  FEED: 'post_',
  REELS: 'reel_',
  STORY: 'story_',
}

export function AnnotationForm({ data, categories, visualFormats, onSubmit, onSkip, onFormatUpdated }: Props) {
  const { heuristic } = data

  const filteredFormats = useMemo(() => {
    const prefix = FORMAT_PREFIX[data.post.media_product_type]
    if (!prefix) return visualFormats
    return visualFormats.filter(vf => vf.name.startsWith(prefix))
  }, [visualFormats, data.post.media_product_type])

  const [categoryId, setCategoryId] = useState<number | null>(null)
  const [visualFormatId, setVisualFormatId] = useState<number | null>(null)
  const [strategy, setStrategy] = useState<'Organic' | 'Brand Content' | null>(null)

  useEffect(() => {
    setCategoryId(heuristic.category_id)
    setVisualFormatId(heuristic.visual_format_id)
    setStrategy(heuristic.heuristic_strategy as 'Organic' | 'Brand Content' | null)
  }, [data.post.ig_media_id])

  const canSubmit = categoryId !== null && visualFormatId !== null && strategy !== null

  const handleSubmit = useCallback(() => {
    if (canSubmit) onSubmit(categoryId!, visualFormatId!, strategy!)
  }, [canSubmit, categoryId, visualFormatId, strategy, onSubmit])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      if (e.key === 'Enter' && canSubmit) { e.preventDefault(); handleSubmit() }
      if (e.key === 'Escape') { e.preventDefault(); onSkip() }
      if (e.key === '1') setStrategy('Organic')
      if (e.key === '2') setStrategy('Brand Content')
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [canSubmit, handleSubmit, onSkip])

  const categoryName = categories.find(c => c.id === categoryId)?.name
  const selectedFormat = filteredFormats.find(vf => vf.id === visualFormatId)
    ?? visualFormats.find(vf => vf.id === visualFormatId)
  const formatName = selectedFormat?.name
  const categoryChanged = categoryId !== heuristic.category_id
  const formatChanged = visualFormatId !== heuristic.visual_format_id
  const strategyChanged = strategy !== heuristic.heuristic_strategy

  return (
    <div className="bg-white rounded-lg border border-neutral-200 overflow-hidden">
      {/* Heuristique v0 */}
      <div className="px-4 py-3 bg-neutral-50 border-b border-neutral-100">
        <p className="text-[11px] font-medium text-neutral-400 mb-2">Heuristique v0</p>
        <div className="flex gap-1.5 flex-wrap">
          {heuristic.heuristic_category && (
            <Badge variant="secondary" className="text-[11px] bg-neutral-100 text-neutral-600 hover:bg-neutral-100">
              {heuristic.heuristic_category}
            </Badge>
          )}
          {heuristic.heuristic_visual_format && (
            <Badge variant="secondary" className="text-[11px] bg-neutral-100 text-neutral-600 hover:bg-neutral-100">
              {heuristic.heuristic_visual_format}
            </Badge>
          )}
          {heuristic.heuristic_strategy && (
            <Badge variant="secondary" className="text-[11px] bg-neutral-100 text-neutral-600 hover:bg-neutral-100">
              {heuristic.heuristic_strategy}
            </Badge>
          )}
          {heuristic.heuristic_subcategory && (
            <Badge variant="outline" className="text-[11px] text-neutral-400 border-neutral-200 hover:bg-transparent">
              {heuristic.heuristic_subcategory}
            </Badge>
          )}
        </div>
      </div>

      {/* Formulaire */}
      <div className="p-4 space-y-4">
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label className="text-xs font-medium text-neutral-500">Catégorie</label>
            {categoryChanged && (
              <span className="text-[11px] text-amber-600">modifié</span>
            )}
          </div>
          <Select value={categoryId?.toString() ?? ''} onValueChange={v => setCategoryId(Number(v))}>
            <SelectTrigger className="w-full h-9 text-sm">
              {categoryName ?? <span className="text-neutral-400">Choisir...</span>}
            </SelectTrigger>
            <SelectContent>
              {categories.map(c => (
                <SelectItem key={c.id} value={c.id.toString()} className="text-sm">{c.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label className="text-xs font-medium text-neutral-500">Format visuel</label>
            {formatChanged && (
              <span className="text-[11px] text-amber-600">modifié</span>
            )}
          </div>
          <Select value={visualFormatId?.toString() ?? ''} onValueChange={v => setVisualFormatId(Number(v))}>
            <SelectTrigger className="w-full h-9 text-sm">
              {formatName ?? <span className="text-neutral-400">Choisir...</span>}
            </SelectTrigger>
            <SelectContent>
              {filteredFormats.map(vf => (
                <SelectItem key={vf.id} value={vf.id.toString()} className="text-sm">{vf.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          {selectedFormat && (
            <FormatDescription
              item={selectedFormat}
              onSaved={onFormatUpdated}
            />
          )}
        </div>

        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label className="text-xs font-medium text-neutral-500">Stratégie</label>
            {strategyChanged && (
              <span className="text-[11px] text-amber-600">modifié</span>
            )}
          </div>
          <div className="grid grid-cols-2 gap-1 p-1 bg-neutral-100 rounded-lg">
            <button
              onClick={() => setStrategy('Organic')}
              className={`px-3 py-2 rounded-md text-sm font-medium transition-all ${
                strategy === 'Organic'
                  ? 'bg-white text-neutral-900 shadow-sm'
                  : 'text-neutral-500 hover:text-neutral-700'
              }`}
            >
              Organic
              <kbd className="ml-1.5 text-[10px] text-neutral-400">1</kbd>
            </button>
            <button
              onClick={() => setStrategy('Brand Content')}
              className={`px-3 py-2 rounded-md text-sm font-medium transition-all ${
                strategy === 'Brand Content'
                  ? 'bg-white text-neutral-900 shadow-sm'
                  : 'text-neutral-500 hover:text-neutral-700'
              }`}
            >
              Brand
              <kbd className="ml-1.5 text-[10px] text-neutral-400">2</kbd>
            </button>
          </div>
        </div>
      </div>

      {/* Actions */}
      <div className="px-4 py-3 border-t border-neutral-100 flex gap-2">
        <Button variant="ghost" onClick={onSkip} className="flex-1 h-10 text-sm text-neutral-500">
          Skip
          <kbd className="ml-1.5 text-[10px] text-neutral-400 bg-neutral-100 px-1.5 py-0.5 rounded">esc</kbd>
        </Button>
        <Button
          onClick={handleSubmit}
          disabled={!canSubmit}
          className="flex-1 h-10 text-sm bg-neutral-900 hover:bg-neutral-800"
        >
          Valider
          <kbd className="ml-1.5 text-[10px] text-neutral-400 bg-neutral-700 px-1.5 py-0.5 rounded">&#9166;</kbd>
        </Button>
      </div>
    </div>
  )
}
