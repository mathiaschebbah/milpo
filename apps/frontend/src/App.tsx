import { useAnnotation } from '@/hooks/useAnnotation'
import { MediaViewer } from '@/components/MediaViewer'
import { AnnotationForm } from '@/components/AnnotationForm'
import { Progress } from '@/components/ui/progress'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'

function App() {
  const { current, done, progress, categories, visualFormats, loading, submit, skip } = useAnnotation()

  const pct = progress.total > 0 ? (progress.annotated / progress.total) * 100 : 0

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b px-6 py-4">
        <div className="max-w-2xl mx-auto flex items-center justify-between">
          <h1 className="text-xl font-semibold tracking-tight">HILPO — Annotation</h1>
          <div className="flex items-center gap-3">
            <span className="text-sm text-muted-foreground">
              {progress.annotated} / {progress.total}
            </span>
            <Progress value={pct} className="w-32" />
          </div>
        </div>
      </header>

      <main className="max-w-2xl mx-auto p-6 space-y-4">
        {loading && !current && (
          <div className="text-center py-20 text-muted-foreground">Chargement...</div>
        )}

        {done && (
          <div className="text-center py-20">
            <h2 className="text-2xl font-semibold">Annotation terminée</h2>
            <p className="text-muted-foreground mt-2">
              {progress.annotated} posts annotés sur {progress.total}
            </p>
          </div>
        )}

        {current && !done && (
          <>
            <div className="flex items-center gap-2">
              <Badge>{current.post.media_product_type}</Badge>
              <Badge variant="outline">{current.post.media_type}</Badge>
              {current.post.shortcode && (
                <a
                  href={`https://www.instagram.com/p/${current.post.shortcode}/`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-muted-foreground hover:underline ml-auto"
                >
                  Voir sur Instagram
                </a>
              )}
            </div>

            <MediaViewer media={current.media} />

            {current.post.caption && (
              <>
                <Separator />
                <p className="text-sm text-muted-foreground whitespace-pre-line line-clamp-4">
                  {current.post.caption}
                </p>
              </>
            )}

            <Separator />

            <AnnotationForm
              data={current}
              categories={categories}
              visualFormats={visualFormats}
              onSubmit={submit}
              onSkip={skip}
            />
          </>
        )}
      </main>
    </div>
  )
}

export default App
