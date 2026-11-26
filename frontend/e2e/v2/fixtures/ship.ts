import { projectId } from './connect-a'

export const created = '2026-11-25T10:30:00Z'
export const generationId = '29342176-4b5c-468c-91d4-29bbda2dc45a'
export const proposalId = '31ea8606-294b-4a92-acb0-5373f20f5c66'
export const specHash = 'd6a224a962b0cf94c79347a1a9cac9b59fbc087ef49eeb52d66449eb571750feb'
export const deployment = {
  project_id: projectId, enabled: true, cloud: 'aws', region: 'eu-west-1', github_repo: 'team/warehouse',
  version: 3, updated_at: created,
  environments: ['dev', 'prod'].map(name => ({
    name, profile: name === 'prod' ? 'medium' : 'small', min_instances: null, max_instances: null, cpu: null,
    memory: null, db_storage_gb: null, db_high_availability: null, deletion_protection: null,
  })),
}
export const plan = {
  cloud: 'aws', region: 'eu-west-1', valid_sizes: [[512, 1024], [1024, 2048]],
  notes: ['ECS Fargate and RDS PostgreSQL run in private subnets.'],
  environments: deployment.environments.map((environment, index) => ({
    ...environment, cpu: index ? 1024 : 512, memory: index ? 2048 : 1024, min_instances: index + 1,
    max_instances: index ? 6 : 2, db_class: index ? 'db.m7g.large' : 'db.t4g.small', db_storage_gb: index ? 50 : 20,
    db_high_availability: !!index, deletion_protection: !!index,
    tfvars: 'aws_region = "eu-west-1"\nenvironment = "' + environment.name + '"',
  })),
}
export const generation = {
  id: generationId, project_id: projectId, spec_hash: specHash, file_count: 2, total_size: 12304, created_at: created,
}
export const files = [
  { path: 'README.md', size: 3460 }, { path: 'app/main.py', size: 8844 },
]
export const migration = {
  text: '1. Drop field users.nickname (destructive)', old_spec_hash: 'a' + specHash, new_spec_hash: specHash,
  first_generation: false, old_snapshot_unusable: false, against_generation_id: generationId, allow_destructive_required: true,
  plan: {
    steps: [{
      seq: 1, phase: 3, kind: 'drop_field', table: 'users', entity: 'User', field: 'nickname',
      safety: 'destructive', reason: 'The field was removed.', suggested_action: 'Back up existing values.',
      backfill_strategy: null, sql_hint: null, note: null,
    }],
    ignored_sections: [], requires_confirmation: true, requires_backfill: false, highest_safety: 'destructive',
  },
}
export const preview = { spec_hash: specHash, total_files: 2, total_size: 12304, files, migration }
export const scorecard = {
  score: 77, passing: false, checks: [
    { id: 'auth', group: 'security', status: 'pass', detail: '', fix: { action: 'none', route: '' } },
    { id: 'package-drift', group: 'dependency_freshness', status: 'warn', detail: 'The dependency needs an upgrade.', fix: { action: 'open_upgrade', route: 'upgrades' } },
    { id: 'validate-hook', group: 'hook_coverage', status: 'fail', detail: 'One hook needs to be declared again.', fix: { action: 'redeclare_hook', route: 'hooks' } },
  ],
}
export const proposal = {
  id: proposalId, project_id: projectId, base_generation_id: generationId, status: 'open', from_generator_version: '2.0.0',
  to_generator_version: '2.0.1', block_changes: [{ block: 'core', from: '1.0.0', to: '1.0.1', bump: 'patch' }],
  file_count: 1, auto_apply_eligible: false, created_at: created, decided_at: null, created_by: null,
  files: [{ path: 'app/main.py', zone: 'generated', change: 'modified' }], kept: ['app/hooks/custom.py'], patch_size: 48,
  sbom_diff: { changed: [{ name: 'fastapi', from: '1.0.0', to: '1.0.1' }] }, migrations: [], scorecard,
}

export const patch = '--- a/app/main.py\n+++ b/app/main.py\n@@ -1 +1 @@\n-old\n+new\n'
export const paged = <T>(items: T[], page = 1, total = items.length) => ({ items, total, limit: 20, offset: (page - 1) * 20 })

export const shipFixture: Record<string, unknown> = {
  '/deployment': deployment, '/deployment/issues': { issues: [] }, '/deployment/plan': plan,
  '/generations': paged([generation]), '/validate': { valid: true, issues: [] }, '/generate/preview': preview,
  ['/generation/' + generationId]: { ...generation, spec_snapshot: { project: { slug: 'warehouse' } },
    file_manifest: files.map(file => ({ ...file, sha256: specHash })) },
  '/scorecard': scorecard, '/upgrades': paged([proposal]),
  ['/upgrades/' + proposalId]: proposal,
}
