import type { AuthorizationModel, AuthorizationSettings, AuthorizationWrite, Policy } from '../../api/types'

/** The PUT body for saving authorization: what changed, plus everything else exactly as loaded.
 *  field_access is carried through unchanged so saving policies never wipes the field rules. */
export function authorizationWriteBody(
  settings: AuthorizationSettings,
  patch: Partial<{ model: AuthorizationModel; policies: Policy[]; attachments: Record<string, string[]> }>,
): AuthorizationWrite {
  return {
    model: patch.model ?? settings.model,
    policies: patch.policies ?? settings.policies,
    attachments: patch.attachments ?? settings.attachments,
    field_access: settings.field_access ?? [],
    expected_version: settings.version,
  }
}
