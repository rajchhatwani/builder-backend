import { useState } from 'react'
import { useT } from '../../../i18n'
import { ConfirmDestructive, Form, ListRow } from '../../../patterns'
import { Alert, Badge, Button, Card, Row, Stack, Textarea } from '../../../ui'
import { guidedLimits, validators } from '../../../validators'
import { errorCode, fieldMessage, serverMessage } from '../api/guided'
import type { MapItem, RequirementQuestion, useMapWrite } from '../api/guided'
import { useGuidedError } from './GuidedFeedback'

type Write = ReturnType<typeof useMapWrite>['mutateAsync']

export function RequirementDetails({ item, canEdit, busy, write }: { item: MapItem; canEdit: boolean; busy: boolean; write: Write }) {
  const t = useT()
  const [editing, setEditing] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const describeError = useGuidedError()
  const outOfScope = item.status === 'out_of_scope'
  const source = [item.source_doc || t('intake.yourPrompt'), item.source_page && t('intake.sourcePage', { page: item.source_page }), item.source_section]
    .filter(Boolean).join(t('intake.sourceSeparator'))
  const textError = fieldMessage(error, 'text') || (errorCode(error) === 'invalid_text' ? serverMessage(error) : undefined)
  const coverageError = fieldMessage(error, 'covered_by')
  const status = item.status === 'covered' || outOfScope ? item.status : 'open'
  const statusText = t(`intake.itemStatus.${status}`)

  async function changeScope() {
    setError(null)
    try {
      await write({ kind: 'item', item: item.id, body: { status: outOfScope ? 'open' : 'out_of_scope' } })
    } catch (failure) {
      setError(failure)
      throw failure
    }
  }

  return <Card data-testid="req-item"><Stack gap={2}>
    <strong>{t('common.serverText', { text: item.text })}</strong>
    <p className="v2-small v2-muted" data-testid="req-source">{t('intake.from', { source })}</p>
    <Row><span data-testid="req-status"><Badge tone={status === 'covered' ? 'success' : 'neutral'}>
      {item.covered_by ? t('intake.coveredByValue', { status: statusText, name: item.covered_by }) : statusText}
    </Badge></span></Row>
    {item.subject && <ListRow title={t('intake.subject')} detail={t('common.serverText', { text: item.subject })} />}
    {item.value && <ListRow title={t('intake.value')} detail={t('common.serverText', { text: item.value })} />}
    {canEdit && (editing ? <>
      <Form pending={busy} submitLabel={t('common.save')} fields={[
        { name: 'text', label: t('intake.itemText'), validate: [validators.required, validators.length(guidedLimits.item)],
          control: attrs => <Textarea {...attrs} defaultValue={item.text} maxLength={guidedLimits.item} /> },
        { name: 'covered_by', label: t('intake.coveredBy'), validate: [validators.length(guidedLimits.coveredBy)],
          control: attrs => <Textarea {...attrs} rows={1} defaultValue={item.covered_by ?? ''} maxLength={guidedLimits.coveredBy} /> },
      ]} serverErrors={{
        ...(textError && { text: { key: 'common.serverText', values: { text: textError } } }),
        ...(coverageError && { covered_by: { key: 'common.serverText', values: { text: coverageError } } }),
      }} onSubmit={values => {
        const text = String(values.get('text')).trim()
        const coveredBy = String(values.get('covered_by')).trim() || null
        setError(null)
        void write({ kind: 'item', item: item.id, body: { text, covered_by: coveredBy } })
          .then(() => setEditing(false), setError)
      }} />
      <Row><Button disabled={busy} onClick={() => { setEditing(false); setError(null) }}>{t('guided.cancel')}</Button></Row>
    </> : <Row>
      <Button disabled={busy} onClick={() => { setEditing(true); setError(null) }}>{t('intake.edit')}</Button>
      {outOfScope ? <Button disabled={busy} onClick={() => { void changeScope().catch(() => undefined) }}>{t('intake.restoreScope')}</Button>
        : <ConfirmDestructive trigger={<Button variant="danger" disabled={busy}>{t('intake.exclude')}</Button>}
          title={t('intake.excludeTitle')} description={t('intake.excludeDescription')} action={t('intake.exclude')}
          pending={busy} error={error ? describeError(error) : undefined} onConfirm={changeScope} />}
    </Row>)}
    {error != null && !textError && !coverageError && <Alert tone="danger">{describeError(error)}</Alert>}
  </Stack></Card>
}

export function RequirementQuestionCard({ question, canEdit, busy, write }: {
  question: RequirementQuestion; canEdit: boolean; busy: boolean; write: Write
}) {
  const t = useT()
  const describeError = useGuidedError()
  const [revising, setRevising] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const resolved = question.state !== 'open'
  const answerError = fieldMessage(error, 'answer') || (errorCode(error) === 'invalid_answer' ? serverMessage(error) : undefined)
  const showForm = canEdit && (!resolved || revising)

  async function send(body: { answer?: string; accept_assumption?: boolean }) {
    setError(null)
    try {
      await write({ kind: 'answer', question: question.id, body })
      setRevising(false)
    } catch (failure) { setError(failure) }
  }

  return <Card data-testid="req-question"><Stack gap={2}>
    <strong>{t('common.serverText', { text: question.text })}</strong>
    {question.assumption && <p className="v2-muted">{t('intake.assumption', { text: question.assumption })}</p>}
    {resolved && <p data-testid="question-resolved">{question.state === 'assumed' ? t('intake.assumptionAccepted')
      : t('intake.answerValue', { text: question.answer ?? '' })}</p>}
    {showForm && <>
      <Form key={question.state} pending={busy} submitLabel={t('intake.answer')} fields={[
        { name: 'answer', label: t('intake.yourAnswer'), validate: [validators.required, validators.length(guidedLimits.answer)],
          control: attrs => <Textarea {...attrs} rows={2} maxLength={guidedLimits.answer} defaultValue={question.answer ?? ''} /> },
      ]} serverErrors={answerError ? { answer: { key: 'common.serverText', values: { text: answerError } } } : undefined}
      onSubmit={value => { void send({ answer: String(value.get('answer')).trim() }) }} />
      <Row>
        {question.assumption && question.state !== 'assumed' && <Button disabled={busy} onClick={() => { void send({ accept_assumption: true }) }}>{t('intake.acceptAssumption')}</Button>}
        {revising && <Button disabled={busy} onClick={() => { setRevising(false); setError(null) }}>{t('guided.cancel')}</Button>}
      </Row>
    </>}
    {canEdit && resolved && !revising && <Row><Button disabled={busy} onClick={() => setRevising(true)}>{t('intake.changeAnswer')}</Button></Row>}
    {error != null && !answerError && <Alert tone="danger">{describeError(error)}</Alert>}
  </Stack></Card>
}
