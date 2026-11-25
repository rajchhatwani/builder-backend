import { useEffect, useState } from 'react'

export function usePdfUrl(blob?: Blob) {
  const [url, setUrl] = useState<string>()
  useEffect(() => {
    if (!blob) { setUrl(undefined); return }
    const url = URL.createObjectURL(blob)
    setUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [blob])
  return url
}

