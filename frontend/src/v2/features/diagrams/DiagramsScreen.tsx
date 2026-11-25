import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { lazy, Suspense, useEffect, useMemo, useRef } from 'react'
import { useT } from '../../i18n'
import { ConflictBanner, PageHeader, ReadOnlyNote } from '../../patterns'
import { openInEditor } from '../../patterns/editorLink'
import { defaultSectionSearch, type ProjectSection } from '../../projectNavigation'
import { Alert, Badge, Button, Card, EmptyState, ErrorBoundary, Field, Grid, Row, Select, Skeleton, Stack } from '../../ui'
import { historyPageSize, sourceError, specOptions, useDiagramSources } from './api/diagrams'
import { audiences, filterCatalogue, topics } from './catalogue'
import type { DiagramId } from './catalogue'
import { DiagramContent } from './components/DiagramContent'
import { hasDiagramData, record, str } from './model'
import { buildDiagram } from './sourcedViews'
import './diagrams.css'

const TraceView = lazy(() => import('./components/TraceView'))

function SourceLink({ projectId, section, label, base, preview }: {
  projectId: string; section: ProjectSection; label: string; base?: number; preview?: string
}) {
  return <Button asChild>{section === 'overview' ?
    <Link to="/projects/$projectId/overview" params={{ projectId }} search={{ preview }}>{label}</Link> :
    <Link to="/projects/$projectId/$section" params={{ projectId, section }}
      search={{ ...defaultSectionSearch(section), base, preview }}>{label}</Link>}</Button>
}

function LoadProblem({ error, retry }: { error: unknown; retry: () => void }) {
  const t = useT()
  const status = sourceError(error)
  if (status === 409) return <ConflictBanner onReload={retry}>{t('diagrams.conflict')}</ConflictBanner>
  return <Alert tone="danger" action={status !== 403 && status !== 404 &&
    <Button onClick={retry}>{t('common.retry')}</Button>}>
    {t(status === 403 || status === 404 ? 'diagrams.forbidden' : 'diagrams.error')}
  </Alert>
}

export default function DiagramsScreen({ projectId, viewer = false }: { projectId: string; viewer?: boolean }) {
  const t = useT()
  const search = useSearch({ strict: false })
  const navigate = useNavigate({ from: '/projects/$projectId/$section' })
  const titleRef = useRef<HTMLHeadingElement>(null)
  const focusTarget = useRef<DiagramId>(undefined)
  const { current: audience, diagrams } = filterCatalogue(search.audience)
  const selected = diagrams.find(diagram => diagram.id === search.view)
    ?? diagrams.find(diagram => diagram.id === 'D05') ?? diagrams[0]
  const { id, support, source: sourceSection } = selected
  const title = t('diagrams.names.' + id)
  const spec = useQuery(specOptions(projectId))
  const page = search.page ?? 1
  const loaded = Boolean(spec.data && hasDiagramData(spec.data))
  const { data, source } = useDiagramSources(projectId, id, search.diagramPick, page, loaded)
  const diagram = useMemo(() => loaded && spec.data && !source?.isPending && !source?.isError
    ? buildDiagram(id, spec.data, data, (key, values) => t('diagrams.words.' + key, values), search.diagramPick, audience)
    : undefined, [loaded, spec.data, id, data, source?.isPending, source?.isError, t, search.diagramPick, audience])
  const projectName = str(record(spec.data?.project).name)
  const sourceLink = (section: ProjectSection, label = t('diagrams.openSource', { section: t('nav.' + section) }), base?: number) =>
    <SourceLink projectId={projectId} section={section} label={label} base={base} preview={search.preview} />

  useEffect(() => {
    if (focusTarget.current === id) {
      titleRef.current?.focus()
      focusTarget.current = undefined
    }
  }, [id])

  function selectDiagram(value: string, moveFocus = false) {
    if (moveFocus && value === id) titleRef.current?.focus()
    else if (moveFocus) focusTarget.current = diagrams.find(entry => entry.id === value)?.id
    void navigate({ search: previous => ({ ...previous, view: value, diagramPick: undefined, page: undefined, diagramPages: undefined }) })
  }

  return <Stack className="v2-diagrams" gap={5}>
    <PageHeader title={t('diagrams.title')} description={t('diagrams.intro')} />
    {spec.isError ? <LoadProblem error={spec.error} retry={() => void spec.refetch()} /> :
      spec.isPending ? <Card className="v2-diagrams-loading"><Skeleton label={t('diagrams.loading')} lines={8} /></Card> :
      !loaded ? <EmptyState title={t('diagrams.empty')} description={t('diagrams.emptyHint')}
        action={sourceLink('model', t('diagrams.openModel'))} /> : <>
        {viewer && <ReadOnlyNote>{t('diagrams.readOnly')}</ReadOnlyNote>}
        <Grid className="v2-diagrams-filters">
          <Field label={t('diagrams.audience')}>{attributes => <Select triggerProps={attributes} value={audience}
            options={audiences.map(value => ({ value, label: t('diagrams.audiences.' + value) }))}
            onValueChange={value => {
              const { diagrams: options } = filterCatalogue(value)
              const keep = options.some(option => option.id === id)
              void navigate({ search: previous => ({ ...previous, audience: value, view: keep ? id : undefined,
                diagramPick: keep ? previous.diagramPick : undefined, page: keep ? previous.page : undefined,
                diagramPages: keep ? previous.diagramPages : undefined }) })
            }} />}</Field>
          <Field label={t('diagrams.diagram')}>{attributes => <Select triggerProps={attributes} value={id}
            options={diagrams.map(diagram => ({ value: diagram.id, label: t('diagrams.names.' + diagram.id) }))}
            onValueChange={value => selectDiagram(value)} />}</Field>
        </Grid>
        <Card aria-labelledby="diagram-title">
          <Stack gap={4}>
            <Stack gap={2}>
              <Row><h2 id="diagram-title" tabIndex={-1} ref={titleRef}>{title}</h2>
                <Badge tone={support === 'Y' ? 'success' : support === 'P' ? 'warning' : 'neutral'}>
                  {t('diagrams.support.' + support)}
                </Badge>
              </Row>
              {support !== 'Y' && <p className="v2-muted">{t('diagrams.missing', { gap: t('diagrams.gaps.' + id) })}</p>}
              {projectName && <p className="v2-muted">
                {t('diagrams.source', { project: projectName })}
              </p>}
            </Stack>
            {source?.isError ? id === 'D41' && sourceError(source.error) === 404 && search.diagramPick ?
              <Alert tone="danger" action={<Button onClick={() => void navigate({ search: previous => ({
                ...previous, diagramPick: undefined, diagramPages: undefined,
              }) })}>{t('diagrams.resetVersion')}</Button>}>{t('diagrams.noVersion')}</Alert> :
              <LoadProblem error={source.error} retry={() => void source.refetch()} /> :
              source?.isPending ? <Skeleton label={t('diagrams.loading')} lines={5} /> :
              id === 'D36' ? <ErrorBoundary><Suspense fallback={<Skeleton label={t('diagrams.loading')} lines={5} />}><TraceView page={page}
                onPage={next => void navigate({ search: previous => ({ ...previous, page: next }) })} /></Suspense></ErrorBoundary> :
              diagram && <Stack gap={4}>
                {diagram.picker && diagram.picker.options.length > 0 && <Field label={diagram.picker.label}>
                  {attributes => <Select triggerProps={attributes} value={diagram.picker!.value} options={diagram.picker!.options}
                    onValueChange={value => void navigate({ search: previous => ({ ...previous, diagramPick: value, diagramPages: undefined }) })} />}
                </Field>}
                {diagram.note && <p className="v2-muted">{diagram.note}</p>}
                <DiagramContent diagram={diagram} title={title} pages={search.diagramPages} heatmap={id === 'D13'}
                  onPage={(table, next) => void navigate({ search: previous => ({ ...previous, diagramPages: { ...previous.diagramPages, [table]: next } }) })}
                  onFile={path => <Button asChild><Link {...openInEditor({ projectId, path })}>
                    {t('diagrams.openGeneratedCode', { path })}
                  </Link></Button>} />
                {id === 'D41' && Boolean(data.totalOps) && <Row>
                  <Button disabled={page <= 1} onClick={() => void navigate({ search: previous => ({
                    ...previous, page: page - 1, diagramPick: undefined, diagramPages: undefined,
                  }) })}>{t('diagrams.previousChanges')}</Button>
                  <Button disabled={page * historyPageSize >= (data.totalOps ?? 0)} onClick={() => void navigate({ search: previous => ({
                    ...previous, page: page + 1, diagramPick: undefined, diagramPages: undefined,
                  }) })}>{t('diagrams.moreChanges')}</Button>
                  {sourceLink('specdiff', t('diagrams.openDiff'), data.version)}
                </Row>}
              </Stack>}
            {sourceSection && <Row className="v2-diagrams-section">{sourceLink(sourceSection)}</Row>}
          </Stack>
        </Card>
        <section aria-labelledby="diagram-catalogue-title">
          <Stack gap={4}>
            <h2 id="diagram-catalogue-title">{t('diagrams.catalogue', { count: diagrams.length })}</h2>
            {Object.entries(topics).map(([topic, ids]) => {
              const entries = ids.flatMap(id => diagrams.filter(item => item.id === id))
              return entries.length > 0 && <section key={topic} aria-labelledby={'diagram-topic-' + topic}>
                <Stack gap={2}>
                  <h3 id={'diagram-topic-' + topic}>{t('diagrams.topics.' + topic)}</h3>
                  <Grid className="v2-diagrams-choices" gap={2}>
                    {entries.map(entry => <Button key={entry.id} className="v2-diagrams-choice"
                      aria-pressed={entry.id === id} onClick={() => selectDiagram(entry.id, true)}>
                      <span className="v2-diagrams-choice-label"><span>{t('diagrams.names.' + entry.id)}</span><small>{t('diagrams.support.' + entry.support)}</small></span>
                    </Button>)}
                  </Grid>
                </Stack>
              </section>
            })}
          </Stack>
        </section>
      </>}
  </Stack>
}
