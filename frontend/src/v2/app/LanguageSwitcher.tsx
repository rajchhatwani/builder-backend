import { useLanguage, useT } from '../i18n'
import { Alert, Button, Select } from '../ui'

export function LanguageSwitcher() {
  const t = useT()
  const { language, choose } = useLanguage()
  return <Select value={language} onValueChange={value => { if (value === 'en') choose(value) }}
    options={[{ value: 'en', label: t('language.en') }]} triggerProps={{ 'aria-label': t('language.label') }} />
}

export function LanguageSuggestion() {
  const t = useT()
  const { language, suggest, dismissSuggestion, choose } = useLanguage()
  if (!suggest) return null
  return (
    <Alert action={<Button onClick={() => { choose(language); dismissSuggestion() }}>{t('language.keep')}</Button>}>
      {t('language.suggest', { language: t(`language.${language}`) })}
    </Alert>
  )
}
