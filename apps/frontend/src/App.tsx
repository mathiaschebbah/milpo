import { useState } from 'react'
import { useAnnotation } from '@/hooks/useAnnotation'
import { MediaViewer } from '@/components/MediaViewer'
import { AnnotationForm } from '@/components/AnnotationForm'
import { PostGrid } from '@/components/PostGrid'
import { TaxonomyPage } from '@/components/TaxonomyPage'
import { Progress } from '@/components/ui/progress'
import { Badge } from '@/components/ui/badge'

type View = 'annotate' | 'grid' | 'taxonomy'

function App() {
  const [view, setView] = useState<View>('annotate')
  const { current, done, progress, categories, visualFormats, loading, submit, skip, loadPost, updateVisualFormat, mode, switchMode } = useAnnotation()

  const pct = progress.total > 0 ? (progress.annotated / progress.total) * 100 : 0

  return (
    <div className="min-h-screen bg-neutral-50">
      <header className="bg-white border-b border-neutral-200 px-6 py-3 sticky top-0 z-10">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h1 className="text-sm font-semibold tracking-tight text-neutral-900">HILPO</h1>

            <div className="flex p-0.5 bg-neutral-100 rounded-md">
              <button
                onClick={() => setView('annotate')}
                className={`px-2.5 py-1 text-xs font-medium rounded transition-all ${
                  view === 'annotate'
                    ? 'bg-white text-neutral-900 shadow-sm'
                    : 'text-neutral-500 hover:text-neutral-700'
                }`}
              >
                Annoter
              </button>
              <button
                onClick={() => setView('grid')}
                className={`px-2.5 py-1 text-xs font-medium rounded transition-all ${
                  view === 'grid'
                    ? 'bg-white text-neutral-900 shadow-sm'
                    : 'text-neutral-500 hover:text-neutral-700'
                }`}
              >
                Dataset
              </button>
              <button
                onClick={() => setView('taxonomy')}
                className={`px-2.5 py-1 text-xs font-medium rounded transition-all ${
                  view === 'taxonomy'
                    ? 'bg-white text-neutral-900 shadow-sm'
                    : 'text-neutral-500 hover:text-neutral-700'
                }`}
              >
                Taxonomie
              </button>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {view === 'annotate' && (
              <button
                onClick={() => switchMode(mode === 'next' ? 'doubtful' : 'next')}
                className={`px-2.5 py-1 text-xs font-medium rounded transition-all ${
                  mode === 'doubtful'
                    ? 'bg-amber-100 text-amber-700 ring-1 ring-amber-300'
                    : 'text-neutral-500 hover:text-neutral-700 bg-neutral-100'
                }`}
              >
                {mode === 'doubtful' ? 'Pas sur' : 'Nouveaux'}
              </button>
            )}
            <span className="text-xs tabular-nums text-neutral-500">
              {progress.annotated} / {progress.total}
            </span>
            <Progress value={pct} className="w-24 h-1.5" />
            <span className="text-xs font-medium tabular-nums text-neutral-900 bg-neutral-100 px-2 py-0.5 rounded-full">
              {pct.toFixed(1)}%
            </span>
          </div>
        </div>
      </header>

      {view === 'grid' && (
        <main className="max-w-6xl mx-auto p-6">
          <PostGrid onOpenPost={(id) => { loadPost(id); setView('annotate') }} />
        </main>
      )}

      {view === 'taxonomy' && (
        <main className="max-w-6xl mx-auto p-6">
          <TaxonomyPage />
        </main>
      )}

      {view === 'annotate' && (
        <>
          {loading && !current && (
            <div className="flex items-center justify-center h-[80vh]">
              <p className="text-sm text-neutral-400 animate-pulse">Chargement...</p>
            </div>
          )}

          {done && (
            <div className="flex flex-col items-center justify-center h-[80vh] gap-3">
              <div className="text-4xl">&#10003;</div>
              <h2 className="text-lg font-semibold text-neutral-900">Annotation terminée</h2>
              <p className="text-sm text-neutral-500">
                {progress.annotated} posts annotés
              </p>
            </div>
          )}

          {current && !done && (
            <main className="max-w-6xl mx-auto p-6">
              <div className="grid grid-cols-1 lg:grid-cols-[1fr_380px] gap-6">
                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <Badge className="bg-neutral-900 text-white text-[11px] hover:bg-neutral-800">
                      {current.post.media_product_type}
                    </Badge>
                    <Badge variant="outline" className="text-[11px]">
                      {current.post.media_type}
                    </Badge>
                    {current.post.split && (
                      <Badge className={`text-[11px] text-white ${
                        current.post.split === 'test'
                          ? 'bg-amber-500 hover:bg-amber-600'
                          : 'bg-blue-500 hover:bg-blue-600'
                      }`}>
                        {current.post.split}
                      </Badge>
                    )}
                    {current.media.length > 1 && (
                      <span className="text-xs text-neutral-400">
                        {current.media.length} slides
                      </span>
                    )}
                    {current.post.shortcode && (
                      <a
                        href={`https://www.instagram.com/p/${current.post.shortcode}/`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-neutral-400 hover:text-neutral-700 transition-colors ml-auto"
                      >
                        Voir sur IG &#8599;
                      </a>
                    )}
                  </div>

                  <MediaViewer media={current.media} />

                  {current.post.caption && (
                    <div className="bg-white rounded-lg border border-neutral-200 p-4">
                      <p className="text-sm leading-relaxed text-neutral-600 whitespace-pre-line text-justify">
                        {current.post.caption}
                      </p>
                    </div>
                  )}
                </div>

                <div className="lg:sticky lg:top-20 lg:self-start">
                  <AnnotationForm
                    data={current}
                    categories={categories}
                    visualFormats={visualFormats}
                    onSubmit={submit}
                    onSkip={skip}
                    onFormatUpdated={updateVisualFormat}
                  />
                </div>
              </div>
            </main>
          )}
        </>
      )}
    </div>
  )
}

export default App
