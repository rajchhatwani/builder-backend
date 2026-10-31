# Setting up single sign-on (SAML or OIDC)

For organization admins on a plan that includes SSO. You need to be an **Admin** or **Owner** of the
organization, signed in with a browser session (API tokens cannot change SSO settings).

Open **Organization → SSO & SCIM** (`#/org/<your-slug>/sso`). Replace `<API>` below with the API
address shown in the SP details on that page, and `<slug>` with your organization's slug.

## 1. Prove you own your e-mail domain

People can only sign in through your identity provider (IdP) with an address on a domain you have
verified. This is what stops anyone else's IdP from signing in your people, and yours from signing in
theirs.

1. In **Domains**, add `example.com`. The page shows a TXT record.
2. At your DNS provider, create it exactly as shown:

   | Type | Name | Value |
   |------|------|-------|
   | TXT  | `_builder-verification.example.com` | the value on the page |

3. Select **Verify**. DNS can take a while to propagate; "TXT record not found" means the record is
   not visible yet, not that something is broken. Keep the record in place: removing the domain from
   the page, or a platform operator releasing it, is how a domain is given up.

A domain can belong to one organization at a time.

## 2. Create the connection in your IdP

Pick one protocol. The page shows the exact values for yours.

### SAML 2.0

| Field in your IdP | Value |
|---|---|
| Single sign-on URL / ACS URL | `<API>/sso/saml/<slug>/acs` (HTTP-POST binding) |
| Audience / SP Entity ID | shown on the page (also in the metadata) |
| SP metadata | `<API>/sso/metadata/<slug>` (import this if your IdP accepts a metadata URL) |
| Name ID format | `emailAddress` |
| Attributes | `email` (required). Optional: `firstName`/`givenName`, `lastName`/`surname`, `displayName` |

The common attribute names of Okta, Microsoft Entra ID, Google Workspace and OneLogin are understood
(`email`, `mail`, `…/claims/emailaddress`, `urn:oid:0.9.2342.19200300.100.1.3`, …).

Requirements on the IdP's response:

- It must be **signed** (the Response or the Assertion), with an asymmetric algorithm (RSA-SHA256 or
  stronger, ECDSA). SHA-1 and HMAC "signatures" are refused.
- Our requests to the IdP are not signed; we require signed assertions (`WantAssertionsSigned`).

In Builder, paste the IdP's **entity ID**, **single sign-on URL** and the **signing certificate**
(PEM). Only the public certificate is needed.

### OpenID Connect

| Field in your IdP | Value |
|---|---|
| Redirect URI | `<API>/sso/oidc/<slug>/callback` |
| Grant type | Authorization code, with PKCE (we always use it) |
| Scopes | `openid email profile` |

In Builder, enter the **discovery URL** (`https://…/.well-known/openid-configuration`), the **client
ID** and the **client secret**. The secret is stored encrypted, is never shown again, and is never
sent to our operators. Leave the secret field empty when you save later changes to keep it.

The ID token must carry `email` and `email_verified: true`. Some providers, such as Microsoft Entra
ID, send no `email_verified` claim; for those an admin can tick **Accept sign-ins that don't say the
e-mail is verified**. Only do that if people cannot change their own e-mail address in your IdP,
otherwise someone could sign in as a colleague. An explicit `email_verified: false` is always
refused.

IdP URLs must be public `https://` addresses. Private-network addresses are refused unless the
platform operator allows them for a self-hosted IdP.

## 3. Test before you switch it on

Select **Test with my own e-mail**. You are sent to your IdP and back. The test works before
activation, never signs anyone in, and tells you whether the IdP signed in *you*. **Check
configuration** validates the certificate and endpoints without a sign-in.

## 4. Switch SSO on

**Turn on** needs at least one verified domain. From then on, the login page asks for an e-mail
first; addresses on your verified domains are sent to your IdP.

Settings that matter:

- **Create accounts on first sign-in (JIT)** and the **role** they receive (Member by default;
  never Owner). Each new person takes a seat; with no free seat they see "no free seats".
- Existing members keep their password sign-in unless you remove their access. Platform staff always
  use their own sign-in and can never sign in through a customer's IdP.
- Pair SSO with **SCIM** (see `SCIM_SETUP.md`) so leavers lose access when your IdP removes them.
- An organization policy can **require two-factor authentication**; SSO sign-ins count as
  multi-factor (your IdP owns that step).

## Troubleshooting

When sign-in fails, the login page shows a message; the reason code is in the address
(`#/login?sso_error=<code>`).

| Code | Meaning | What to do |
|---|---|---|
| `email_domain_not_verified` | The IdP asserted an address on a domain you have not verified | Verify the domain (step 1) |
| `not_provisioned` | No account, and JIT is off | Invite the person, or turn JIT on |
| `seat_limit` | No free seat for a new member | Free a seat or upgrade the plan |
| `bad_signature` | The response was not signed by the certificate you configured | Re-copy the IdP's signing certificate (watch for rollover) |
| `malformed` | The response could not be read | Check the attribute mapping and NameID format |
| `idp_error` | The IdP refused the sign-in | Check the user is assigned to the app in the IdP |
| `invalid_request_state` | The sign-in took more than ten minutes, or moved to another browser | Start again |
| `discovery_failed` / `jwks_failed` | OIDC endpoints unreachable | Check the discovery URL; retry |
| `insecure_url` | A configured URL is not allowed (http, private address) | Use a public https address |
| `sso_unavailable` | SSO is off, or the plan no longer includes it | Turn it on / upgrade |
| `account_suspended` | The account is suspended | Contact your administrator |

Every configuration change and every sign-in outcome is in **Organization → Audit** (`sso.*`
events). Certificates and secrets are never written there.
