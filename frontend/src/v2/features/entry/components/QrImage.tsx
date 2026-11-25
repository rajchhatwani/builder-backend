import { useEffect, useState } from 'react'
import { toDataURL } from 'qrcode'
import { useT } from '../../../i18n'
import { Alert, Skeleton } from '../../../ui'

export default function QrImage({ value }: { value: string }) {
  const t = useT()
  const [image, setImage] = useState<string | null>()
  useEffect(() => {
    let active = true
    void toDataURL(value).then(url => { if (active) setImage(url) }, () => { if (active) setImage(null) })
    return () => { active = false }
  }, [value])
  if (image === null) return <Alert>{t('entry.qrFallback')}</Alert>
  if (!image) return <div className="v2-entry-qr"><Skeleton label={t('entry.qrLoading')} /></div>
  return <img src={image} alt={t('entry.qrLabel')} className="v2-entry-qr" />
}
