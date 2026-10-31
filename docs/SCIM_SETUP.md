# Provisioning people with SCIM 2.0

For organization admins on a plan that includes SCIM (Enterprise). SCIM lets your identity provider
(IdP) create, update and **deactivate** your people in Builder automatically. Set up SSO first
(`SSO_SETUP.md`): accounts that SCIM creates have no password and sign in through your SSO.

You need to be an **Admin** or **Owner**, signed in with a browser session. Open
**Organization → SSO & SCIM → SCIM provisioning**.

## 1. Prerequisites

- At least one **verified domain** (see `SSO_SETUP.md`, step 1). SCIM only provisions addresses on
  domains your organization has verified. Anything else is refused, so one organization can never
  create, rename or remove another's people.
- Platform staff accounts cannot be provisioned.

## 2. Generate the token

Select **Generate token**. The token (`bb_scim_…`) is shown **once**. Copy it into your IdP before
you close the box. We keep only a hash; if you lose it, rotate it.

- **Rotate token** replaces it at once. The old one stops working immediately, so update the IdP
  right away.
- If platform support rotates the token for you (for example after a suspected leak), support never
  sees the new one: SCIM is switched off, and you generate a fresh token, which switches it back on.

Then copy the two URLs shown on the page:

| IdP asks for | Value |
|---|---|
| SCIM base URL / tenant URL | `<API>/scim/v2` |
| Users endpoint (if asked separately) | `<API>/scim/v2/Users` |
| Authentication | HTTP header `Authorization: Bearer <token>` |

## 3. Configure your IdP

Supported: Users and Groups (`GET`, `POST`, `PUT`, `PATCH`, `DELETE`), `ServiceProviderConfig`,
`ResourceTypes`, `Schemas`. Filters: `eq` on `userName`, `externalId`, `emails.value` and `id`
(Users), and on `displayName`, `externalId` and `id` (Groups). Bulk, sorting and ETags are not
supported and are reported as such in `ServiceProviderConfig`.

Map these attributes:

| SCIM attribute | Use |
|---|---|
| `userName` | The person's e-mail address (Okta login / Entra UPN both work) |
| `emails[type eq "work"].value` | Primary e-mail, used if `userName` is not an address |
| `name.givenName`, `name.familyName` | Display name |
| `externalId` | The IdP's own id for the person |
| `active` | `false` deactivates (see below) |

IdP notes: **Okta** sends `PATCH replace {"active": false}`; **Microsoft Entra ID** sends capitalised
operations (`Replace`), `"False"` as a string and path filters like `emails[type eq "work"].value`;
JumpCloud and Google Workspace send full `PUT` bodies. All are handled. Please run your IdP's own
SCIM test (Okta's SCIM test suite, Microsoft's SCIM validator) against your tenant URL when you
first connect.

## 4. What happens to people

| IdP action | In Builder |
|---|---|
| Create user | Joins as a **Member** (or the role their group maps to). Needs a free seat; otherwise the IdP gets a 403 with the reason. New accounts are SSO-only. An existing account on a verified domain is linked, not duplicated, and keeps its password |
| Change name / e-mail | Updated. A new address must stay on a verified domain and must not belong to another account |
| Deactivate (`active: false`) or delete | Removed from the organization and from its projects; API tokens tied to this organization's projects are revoked; the person is **signed out everywhere**. Projects they solely owned are handed to an organization Owner. The account itself, and their personal workspace, remain |
| Reactivate | Rejoins (needs a seat) |
| The last Owner | Never offboarded or demoted by SCIM (the IdP gets a 409) |

Seat counts and billing follow automatically.

## 5. Map groups to roles (optional)

In **Group → role mapping**, map IdP group names to **Admin**, **Member** or **Owner**. Names are
case-insensitive. Each SCIM-managed person gets the highest role of their mapped groups, or Member.
With no mappings, SCIM never changes roles. Only an **Owner** may map a group to Owner or edit a
mapping that contains one. A change in the IdP is applied on its next sync and overrides a role set
manually in **People**.

## 6. Turn off or remove

- **Turn off** keeps the data but the IdP gets `401`.
- **Remove SCIM** deletes the directory records. People stay in the organization.

## Troubleshooting

| IdP sees | Meaning |
|---|---|
| `401` | Wrong or rotated token, or SCIM is switched off or removed |
| `403` | The plan no longer includes SCIM, the organization is scheduled for deletion, or no seat is free |
| `409` `uniqueness` | The user already exists, or the e-mail belongs to another account |
| `409` `mutability` | You tried to offboard or demote the last Owner |
| `400` `invalidFilter` | The IdP used a filter we do not support (only `eq` on the attributes above) |
| `429` | Too many failed authentications from one address; wait a few minutes |

**Last sync** on the page shows when the IdP last connected. Every SCIM change is in
**Organization → Audit** as `scim.*` events with the actor shown as "SCIM". Tokens are never written
there.
