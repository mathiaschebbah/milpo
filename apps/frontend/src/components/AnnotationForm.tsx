import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { PostData } from '@/hooks/useAnnotation'

type Lookup = { id: number; name: string }

type Props = {
  data: PostData
  categories: Lookup[]
  visualFormats: Lookup[]
  onSubmit: (categoryId: number, visualFormatId: number, strategy: 'Organic' | 'Brand Content') => void
  onSkip: () => void
}

export function AnnotationForm({ data, categories, visualFormats, onSubmit, onSkip }: Props) {
  const { heuristic } = data

  const [categoryId, setCategoryId] = useState<number | null>(null)
  const [visualFormatId, setVisualFormatId] = useState<number | null>(null)
  const [strategy, setStrategy] = useState<'Organic' | 'Brand Content' | null>(null)

  useEffect(() => {
    setCategoryId(heuristic.category_id)
    setVisualFormatId(heuristic.visual_format_id)
    setStrategy(heuristic.heuristic_strategy as 'Organic' | 'Brand Content' | null)
  }, [heuristic])

  const canSubmit = categoryId !== null && visualFormatId !== null && strategy !== null

  return (
    <Card>
      <CardContent className="space-y-4 pt-6">
        <div className="flex gap-2 flex-wrap">
          {heuristic.heuristic_category && (
            <Badge variant="secondary">v0: {heuristic.heuristic_category}</Badge>
          )}
          {heuristic.heuristic_visual_format && (
            <Badge variant="secondary">v0: {heuristic.heuristic_visual_format}</Badge>
          )}
          {heuristic.heuristic_strategy && (
            <Badge variant="secondary">v0: {heuristic.heuristic_strategy}</Badge>
          )}
        </div>

        <div className="space-y-3">
          <div>
            <label className="text-sm font-medium mb-1 block">Catégorie</label>
            <Select
              value={categoryId?.toString() ?? ''}
              onValueChange={v => setCategoryId(Number(v))}
            >
              <SelectTrigger>
                <SelectValue placeholder="Choisir une catégorie" />
              </SelectTrigger>
              <SelectContent>
                {categories.map(c => (
                  <SelectItem key={c.id} value={c.id.toString()}>{c.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div>
            <label className="text-sm font-medium mb-1 block">Format visuel</label>
            <Select
              value={visualFormatId?.toString() ?? ''}
              onValueChange={v => setVisualFormatId(Number(v))}
            >
              <SelectTrigger>
                <SelectValue placeholder="Choisir un format" />
              </SelectTrigger>
              <SelectContent>
                {visualFormats.map(vf => (
                  <SelectItem key={vf.id} value={vf.id.toString()}>{vf.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div>
            <label className="text-sm font-medium mb-1 block">Stratégie</label>
            <div className="flex gap-2">
              <Button
                variant={strategy === 'Organic' ? 'default' : 'outline'}
                onClick={() => setStrategy('Organic')}
                className="flex-1"
              >
                Organic
              </Button>
              <Button
                variant={strategy === 'Brand Content' ? 'default' : 'outline'}
                onClick={() => setStrategy('Brand Content')}
                className="flex-1"
              >
                Brand
              </Button>
            </div>
          </div>
        </div>

        <div className="flex gap-2 pt-2">
          <Button variant="ghost" onClick={onSkip} className="flex-1">
            Skip
          </Button>
          <Button
            onClick={() => canSubmit && onSubmit(categoryId!, visualFormatId!, strategy!)}
            disabled={!canSubmit}
            className="flex-1"
          >
            Valider
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
