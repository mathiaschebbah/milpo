import { useState } from 'react'

type Media = {
  media_url: string | null
  thumbnail_url: string | null
  media_type: string
  media_order: number
}

export function MediaViewer({ media }: { media: Media[] }) {
  const [index, setIndex] = useState(0)

  if (media.length === 0) {
    return <div className="flex items-center justify-center h-96 bg-muted rounded-lg text-muted-foreground">Pas de média</div>
  }

  const item = media[index]
  const url = item.media_type === 'VIDEO' ? item.thumbnail_url : item.media_url

  return (
    <div className="relative">
      {url ? (
        <img
          src={url}
          alt={`Média ${index + 1}`}
          className="w-full h-96 object-contain bg-black rounded-lg"
        />
      ) : (
        <div className="flex items-center justify-center h-96 bg-muted rounded-lg text-muted-foreground">
          Média non disponible
        </div>
      )}

      {media.length > 1 && (
        <div className="absolute bottom-3 left-0 right-0 flex justify-center gap-1.5">
          {media.map((_, i) => (
            <button
              key={i}
              onClick={() => setIndex(i)}
              className={`w-2 h-2 rounded-full transition-colors ${
                i === index ? 'bg-white' : 'bg-white/40'
              }`}
            />
          ))}
        </div>
      )}

      {media.length > 1 && (
        <>
          <button
            onClick={() => setIndex(i => Math.max(0, i - 1))}
            disabled={index === 0}
            className="absolute left-2 top-1/2 -translate-y-1/2 bg-black/50 text-white w-8 h-8 rounded-full disabled:opacity-30"
          >
            ‹
          </button>
          <button
            onClick={() => setIndex(i => Math.min(media.length - 1, i + 1))}
            disabled={index === media.length - 1}
            className="absolute right-2 top-1/2 -translate-y-1/2 bg-black/50 text-white w-8 h-8 rounded-full disabled:opacity-30"
          >
            ›
          </button>
        </>
      )}
    </div>
  )
}
