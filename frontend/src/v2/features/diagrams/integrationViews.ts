import type { Builder, Diagram, Spec, Translate } from './model'
import { active, cell, chain, choose, chooseRows, columns, graph, hub, named, objects, record, str, table, words } from './model'
import { integrations } from './architectureViews'
import { upcomingTimes } from './cron'

const paymentTransitions: Record<string, string[]> = {
  creating: ['requires_payment', 'failed'], requires_payment: ['processing', 'succeeded', 'failed', 'canceled', 'expired'],
  processing: ['succeeded', 'failed'], succeeded: [], failed: ['succeeded'], canceled: ['succeeded'], expired: ['succeeded'],
}
const refundTransitions: Record<string, string[]> = {
  pending_approval: ['requested', 'rejected'], requested: ['submitting', 'failed'],
  submitting: ['pending', 'succeeded', 'failed', 'requested'], pending: ['succeeded', 'failed', 'canceled'],
  succeeded: [], failed: [], canceled: [], rejected: [],
}

const paymentStatus: Builder = (spec, w, selection) => {
  if (!active(spec.payments)) return {}
  const picker = choose(w('stateMachine'), ['payment', 'refund'].map(value => ({ value, label: w(value) })), selection)
  const transitions = picker.value === 'refund' ? refundTransitions : paymentTransitions
  const names = Object.keys(transitions)
  const payable = record(record(spec.payments).payable)
  return {
    ...graph(names.map(name => ({ name })), Object.entries(transitions).flatMap(([from, targets]) =>
      targets.map((to): [number, number] => [names.indexOf(from), names.indexOf(to)]))),
    picker,
    tables: [table([w('mapping'), w('savedValue')], [
      [w('statusField'), cell(payable.status_field)], [w('paymentPending'), cell(payable.status_pending)],
      [w('paid'), cell(payable.status_paid)], [w('partiallyRefunded'), cell(payable.status_partially_refunded)],
      [w('refunded'), cell(payable.status_refunded)],
    ])],
  }
}

const flowTemplates = [
  { label: 'signIn', block: 'auth', builtin: true, steps: ['client', 'auth', 'tokenStore'] },
  { label: 'refreshToken', block: 'auth', builtin: true, steps: ['client', 'auth', 'rotateToken'] },
  { label: 'emailVerification', block: 'auth', builtin: true, setting: ['registration', 'email_verification_required'], steps: ['client', 'auth', 'verifyAccount'] },
  { label: 'passwordReset', block: 'auth', builtin: true, setting: ['password_reset', 'email_magic_link'], steps: ['client', 'auth', 'emailProvider'] },
  { label: 'invitation', block: 'auth', builtin: true, steps: ['invitee', 'auth', 'accountStore'] },
  { label: 'checkout', block: 'payments', steps: ['client', 'payments', 'paymentProvider'] },
  { label: 'refundApproval', block: 'payments', steps: ['reviewer', 'payments', 'paymentsWorker'] },
  { label: 'fileUpload', block: 'storage', steps: ['client', 'storage', 'clamav'] },
  { label: 'outboundWebhook', block: 'webhooks', steps: ['relay', 'webhooks', 'receiver'] },
  { label: 'inboundWebhook', block: 'webhooks', steps: ['provider', 'webhooks', 'handler'] },
  { label: 'documentRender', block: 'documents', steps: ['client', 'documents', 'pdfRenderer'] },
]
const sequences: Builder = (spec, w, selection) => {
  const available = flowTemplates.filter(flow => active(spec[flow.block]) &&
    (!flow.builtin || record(spec.auth).provider === 'builtin') &&
    (!flow.setting || record(record(spec[flow.block])[flow.setting[0]])[flow.setting[1]] === true) &&
    (flow.label !== 'inboundWebhook' || objects(record(spec.webhooks).inbound).length > 0))
  const picker = choose(w('flow'), available.map(flow => ({ value: flow.label, label: w(flow.label) })), selection)
  const chosen = available.find(flow => flow.label === picker.value)
  return chosen ? { ...chain(chosen.steps.map(key => ({ name: w(key) }))), picker, note: w('generatedSequence') } : {}
}

const events: Builder = (spec, w) => {
  if (!active(spec.events)) return {}
  const destinations = ['realtime', 'notifications', 'webhooks'].filter(key => active(spec[key])).map(key => ({ name: w(key) }))
  const rows = [{ name: w('write') }, { name: w('outbox'), detail: str(record(spec.events).adapter) },
    { name: w('relay') }, ...destinations]
  return {
    ...graph(rows, [[0, 1, w('transactionalEvents')], [1, 2, w('relayAfterCommit')],
      ...destinations.map((_, index): [number, number] => [2, index + 3])]),
    tables: [
      columns(w, ['notification', 'event', 'channels'], active(spec.notifications) ? objects(record(spec.notifications).types) : [],
        ['name', 'on_event', 'channels']),
      table([w('webhookEvent')], active(spec.webhooks) ? words(record(spec.webhooks).events).map(name => [name]) : []),
      table([w('entity'), w('event')], objects(spec.entities).flatMap(entity =>
        ['created', 'updated', 'deleted',
          ...(objects(spec.state_machines).some(machine => machine.entity === entity.name) ? ['transitioned'] : [])]
          .map(event => [str(entity.name), w(event)]))),
    ],
  }
}

const jobs: Builder = (spec, w) => {
  if (!active(spec.jobs)) return {}
  const block = record(spec.jobs)
  const jobs = objects(block.jobs)
  const groups = objects(block.worker_groups)
  const schedules = objects(block.schedules)
  const queues = [...new Set([...jobs.map(job => str(job.queue)), ...groups.flatMap(group => words(group.queues))])].filter(Boolean)
  return {
    ...graph([{ name: w('queue'), detail: str(record(block.queue).backend) }, ...queues.map(name => ({ name, detail: w('queue') })),
      ...named(groups, 'placement')], queues.flatMap((queue, i): [number, number][] => [
      [0, i + 1], ...groups.flatMap((group, j): [number, number][] => words(group.queues).includes(queue) ? [[i + 1, queues.length + j + 1]] : []),
    ])),
    tables: [
      table(['job', 'queue', 'handler', 'attempts', 'timeout'].map(key => w(key)), jobs.map(job =>
        [str(job.name), str(job.queue), str(job.handler), cell(record(job.retry).max_attempts), cell(job.timeout_seconds)])),
      table([w('producer'), w('job')], [
        ...schedules.filter(schedule => schedule.enabled !== false).map(schedule => [str(schedule.name), str(schedule.job)]),
        ...(active(spec.workflows) ? objects(record(spec.workflows).workflows).flatMap(workflow =>
          objects(workflow.steps).filter(step => step.kind === 'job').map(step =>
            [[str(workflow.name), str(step.name)].join(' · '), str(step.job)])) : []),
      ]),
    ],
  }
}

const schedules: Builder = (spec, w, selection) => {
  if (!active(spec.jobs)) return {}
  const rows = objects(record(spec.jobs).schedules)
  const { picker, selected } = chooseRows(w('schedule'), rows, selection)
  if (!selected) return {}
  const timezone = str(selected.timezone)
  const times = selected.enabled === false ? undefined : upcomingTimes(str(selected.cron), timezone, Date.now())
  const format = times?.length ? new Intl.DateTimeFormat('en', { timeZone: timezone, dateStyle: 'medium', timeStyle: 'short' }) : undefined
  return {
    picker,
    ...(format && times ? chain(times.map(time => ({ name: format.format(time), detail: timezone }))) : {}),
    tables: [columns(w, ['schedule', 'job', 'cron', 'timeZone', 'enabled', 'missedRun'], rows,
      ['name', 'job', 'cron', 'timezone', 'enabled', 'missed'])],
    note: w(selected.enabled === false ? 'scheduleDisabled' : !times ? 'scheduleCheck' :
      times.length ? 'schedulePreview' : 'scheduleNoMatches'),
  }
}

const workflow: Builder = (spec, w, selection) => {
  if (!active(spec.workflows)) return {}
  const { picker, selected } = chooseRows(w('workflow'), objects(record(spec.workflows).workflows), selection)
  if (!selected) return {}
  const steps = objects(selected.steps)
  const forward = chain(named(steps, 'kind'))
  const reverse = selected.on_failure === 'compensate' ? steps.filter(step => step.compensate).reverse() : []
  return { ...forward, picker,
    tables: [
      table(['step', 'kind', 'job', 'timeout', 'attempts'].map(key => w(key)), steps.map(step =>
        [str(step.name), str(step.kind), cell(step.job), cell(step.timeout_seconds), cell(record(step.retry).max_attempts)])),
      ...(reverse.length ? [columns(w, ['step', 'kind'], reverse, ['name', 'kind'], w('reverseCompensation'))] : []),
    ],
  }
}

const roleTable = (w: Translate, roles: unknown) => table([w('action'), w('roles')], Object.entries(record(roles))
  .map(([action, configured]) => [action, cell(configured) ?? w('noRoles')]))

const payments: Builder = (spec, w) => {
  if (!active(spec.payments)) return {}
  const block = record(spec.payments)
  const payable = record(block.payable)
  const scale = record(block.scale)
  return {
    ...graph([{ name: str(payable.entity) || w('entity'), detail: str(payable.amount_field) }, { name: w('payments') },
      { name: str(block.provider) || w('paymentProvider') }, { name: w('paymentsWorker') }], [[0, 1], [1, 2], [2, 3], [3, 1]]),
    tables: [
      roleTable(w, block.roles),
      table([w('profile'), w('replicas'), w('pgbouncer'), w('kubernetes'), w('refundThreshold')],
        [[cell(scale.profile), cell(scale.api_replicas), cell(scale.pgbouncer), cell(scale.kubernetes), cell(block.refund_approval_threshold_minor)]]),
      ...(paymentStatus(spec, w).tables ?? []),
    ],
  }
}

const storage: Builder = (spec, w) => {
  if (!active(spec.storage)) return {}
  const config = record(spec.storage)
  const security = record(config.security)
  return {
    ...chain([{ name: w('upload') }, { name: w('fileChecks') }, { name: w('clamav') },
      { name: str(config.bucket) || w('objectStore'), detail: str(config.backend) },
      { name: w('download'), detail: str(config.download_mode) }]),
    tables: [roleTable(w, config.roles),
      table(['allowedTypes', 'maxFileMb', 'auditDays', 'rescanDays'].map(key => w(key)),
        [[cell(config.allowed_types), cell(config.max_file_mb), cell(security.audit_retention_days), cell(security.rescan_after_days)]])],
  }
}

const ai: Builder = (spec, w) => {
  const pack = record(record(spec.packs).ai)
  if (!pack.gateway) return {}
  const gateway = record(pack.gateway)
  const providers = objects(gateway.providers)
  const stages = objects(gateway.stages)
  const agents = record(pack.agents)
  const consumers = [{ name: w('documents'), stage: record(pack.documents).stage },
    { name: w('knowledge'), stage: record(pack.knowledge).stage }, ...objects(agents.agents)].filter(consumer => consumer.stage)
  const links = stages.flatMap((stage, i): [number, number][] => {
    const provider = providers.findIndex(row => row.name === stage.provider)
    return provider < 0 ? [] : [[providers.length + i + 1, provider + 1]]
  })
  return {
    ...graph([{ name: w('aiGateway'), detail: str(gateway.region) }, ...named(providers, 'kind'), ...named(stages, 'model')],
      [...stages.map((_, i): [number, number] => [0, providers.length + i + 1]), ...links]),
    tables: [
      columns(w, ['stage', 'provider', 'model', 'fallbackModel'], stages, ['name', 'provider', 'model', 'fallback_model']),
      columns(w, ['consumer', 'stage'], consumers, ['name', 'stage']),
      columns(w, ['agent', 'actions', 'autonomy', 'requiredEval'], objects(agents.agents), ['name', 'actions', 'autonomy', 'require_eval']),
      columns(w, ['action', 'risk', 'maxAutonomy'], objects(agents.actions), ['name', 'risk', 'max_autonomy']),
      columns(w, ['evalSuite', 'agent'], objects(record(pack.evals).suites), ['name', 'agent']),
    ],
  }
}

const booking: Builder = (spec, w, selection) => {
  const block = record(record(spec.packs).booking)
  const { picker, selected } = chooseRows(w('resourceKind'), objects(block.kinds), selection)
  if (!selected) return {}
  const calendar = record(selected.schedule)
  const cancellation = record(block.cancellation)
  return {
    ...chain([{ name: str(selected.name), detail: str(selected.mode) }, { name: w('hold') }, { name: w('booking') }]),
    picker,
    tables: [
      table(['timeZone', 'capacity', 'slotMinutes', 'holdSeconds'].map(key => w(key)),
        [[cell(selected.timezone), cell(selected.capacity), cell(selected.slot_minutes), cell(block.hold_ttl_seconds)]]),
      ...(selected.mode === 'slot' ? [table([w('weekday'), w('openWindows')], ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'].map(day =>
        [w(day), objects(calendar[day]).map(window => [str(window.start), str(window.end)].join('–')).join(', ') || w('closed')]))] : []),
      table(['cancelHours', 'feeMinor', 'currency'].map(key => w(key)),
        [[cell(cancellation.free_until_hours), cell(cancellation.fee_minor), cell(cancellation.currency)]]),
    ],
  }
}

function ledger(spec: Spec, w: Translate): Diagram {
  const money = record(record(spec.packs).money)
  const invoice = record(money.invoicing)
  const mappings = Object.entries({ ...invoice, ...record(invoice.payouts) }).filter(([key, value]) => key.endsWith('_account') && typeof value === 'string' && value)
  const accounts = [...new Set(mappings.map(([, value]) => str(value)))]
  return {
    ...(accounts.length ? hub({ name: w('invoicing') }, accounts.map(name => ({ name }))) : {}),
    tables: [table([w('accountRole'), w('account')], mappings.map(([key, value]) => [key, str(value)]))],
  }
}

export const integrationViews = {
  D08: paymentStatus, D11: sequences, D19: events,
  D20: (spec: Spec, w: Translate) => active(spec.realtime) ? chain([
    { name: w('write') }, { name: w('outbox') }, { name: w('relay') },
    { name: w('sse'), detail: '/realtime/stream' }, { name: w('client'), detail: w('idsOnly') },
  ]) : {},
  D21: jobs, D22: schedules, D23: workflow, D27: integrations, D28: payments, D29: storage, D30: ai, D46: booking, D47: ledger,
}
