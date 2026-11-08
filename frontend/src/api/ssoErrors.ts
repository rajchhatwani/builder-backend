/** `#/login?sso_error=<reason>`: why an SSO sign-in came back without a session. */
const SSO_ERRORS: Record<string, string> = {
  sso_unavailable: "Single sign-on isn't available for this organization right now. Sign in with your password, or ask your admin.",
  email_domain_not_verified: "Your identity provider signed you in with an address on a domain the organization hasn't verified.",
  not_provisioned: "You don't have an account here yet, and this organization doesn't create them automatically. Ask your admin to invite you.",
  seat_limit: 'The organization has no free seats for a new member. Ask your admin.',
  account_suspended: 'This account is suspended. Contact your administrator.',
  staff_account: 'Platform staff accounts sign in with a password, not through an organization’s SSO.',
  invalid_request_state: 'The sign-in took too long or was opened in another browser. Start again.',
  bad_signature: "The identity provider's response couldn't be verified. Ask your admin to check the SSO certificate.",
  idp_error: 'The identity provider refused the sign-in.',
  malformed: "The identity provider's response couldn't be read.",
  discovery_failed: "The identity provider couldn't be reached. Try again in a moment.",
  jwks_failed: "The identity provider's signing keys couldn't be fetched. Try again in a moment.",
  insecure_url: 'The SSO configuration points at an address that is not allowed. Ask your admin.',
  invalid_test_ticket: 'That SSO test link expired. Start the test again from the SSO settings.',
}

export function ssoErrorText(reason: string): string {
  return SSO_ERRORS[reason] ?? `SSO sign-in failed (${reason}).`
}

/** `#/org/<slug>/sso?sso_test=<result>`: what "test with my own e-mail" found. */
export function ssoTestText(result: string): string {
  if (result === 'ok') return 'The test sign-in worked: the identity provider signed you in as you.'
  if (result === 'email_mismatch') return 'You signed in to the identity provider as someone else. Sign out there and test again with your own account.'
  return ssoErrorText(result)
}
