import { Link, useParams } from '@tanstack/react-router'
import { useT } from '../i18n'
import { openInEditor } from '../patterns/editorLink'
import { PageHeader } from '../patterns'
import { isDesktopSection } from '../projectNavigation'
import { Button, DesktopOnlyCard, EmptyState, Stack } from '../ui'
import { LanguageSwitcher } from './LanguageSwitcher'

export function ProjectsScreen() {
  const t = useT()
  return (
    <Stack gap={5}>
      <PageHeader title={t('shell.projects')} />
      <EmptyState title={t('shell.projectLink')} action={<Button asChild><Link to="/sign-in">{t('shell.signIn')}</Link></Button>} />
    </Stack>
  )
}

export function SignInScreen() {
  const t = useT()
  return <Stack gap={5}><PageHeader title={t('shell.signIn')} /><LanguageSwitcher /><Unavailable /></Stack>
}

export function Unavailable() {
  const t = useT()
  const { section, projectId } = useParams({ strict: false })
  if (section === 'generate' && projectId) return <Stack gap={5}>
    <PageHeader title={t('nav.generate')} />
    <Button asChild><Link {...openInEditor({ projectId, source: 'manifest' })}>{t('editor.previewFiles')}</Link></Button>
  </Stack>
  return (
    <Stack gap={5}>
      {section && <PageHeader title={t(`nav.${section}`)} />}
      {section && isDesktopSection(section) && <div className="v2-phone-only"><DesktopOnlyCard /></div>}
      <div className={section && isDesktopSection(section) ? 'v2-phone-hidden' : undefined}>
        <EmptyState title={t('shell.unavailable')} action={<Button asChild>{projectId
          ? <Link to="/projects/$projectId/overview" params={{ projectId }}>{t('status.title')}</Link>
          : <Link to="/projects">{t('shell.projects')}</Link>}</Button>} />
      </div>
    </Stack>
  )
}
