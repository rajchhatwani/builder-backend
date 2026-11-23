# Identity migration runbook (Clinic)

How accounts move into, out of or between apps. Everything here runs INSIDE your own environment
over `identity-v1` files; the builder never sees your users. Password hashes are never written by
any command below unless you pass `--include-hashes` to `export` yourself (do not).

Commands (`python -m app.auth.export ...`): `export`, `import`, `relink [--copy]`,
`keycloak-import`, `impact`, `overlap`. `keycloak-import`, `impact` and `overlap` only read.
## Path (b): an existing app joins a suite hub

1. In the builder open the join impact report (roles become client roles, tenants become
   organisations, client id is the project slug, the realm is derived) and fix every blocker.
2. In the OLD app: `export export --out users.ndjson`, then
   `export impact --hub-users hub.ndjson` (counts, verified-email duplicates with the hub,
   unverified accounts, roles, tenants).
3. `export keycloak-import --out kc.json` and import it in the hub realm (Admin console, Realm
   settings, Action, Partial import). Users arrive WITHOUT credentials and must set a password
   (`UPDATE_PASSWORD`); an unverified e-mail also gets `VERIFY_EMAIL`. The Keycloak user id is the
   local user id.
4. Set `migration.state` to `legacy_read_only`, then `dual` with an explicit window
   (`window_started_at`, `dual_until`, at most 90 days), regenerate and deploy the NEW app with
   `LEGACY_JWT_SECRET` set to the old signing secret (HS256, at least 32 bytes).
5. In the NEW app: `export import users.ndjson`, then
   `export relink --from <legacy issuer> --to <hub issuer> --copy` so a hub token and a legacy
   token reach the same local user (ids, `created_by_id` and tenants never change).
6. During the window both tokens work; legacy ones stop at `dual_until` (fails closed).
7. Set `hub_only` (final), remove `LEGACY_JWT_SECRET`. Legacy access and refresh tokens are
   refused. Old refresh tokens never move: clients sign in at the hub.
8. Lazy password migration is not built: every user sets a new password once.

## Path (c): two independent apps that share people

1. Each side runs `export export --out side.ndjson` (no hashes) and sends the file to the owner of
   the merge. Treat the files as personal data.
2. `export overlap --other other.ndjson` is a dry run: it matches ONLY e-mail addresses verified
   on both sides, lists unverified accounts apart (never matched), and reports collisions, role
   conflicts and tenant slug overlaps. It changes nothing and prints no hashes.
3. Decide per collision. Link in your own reviewed code with
   `identity.link_verified(session, user_id, claims_a, claims_b, trusted_issuers)`: both proofs
   must come from trusted issuers (`AUTH_TRUSTED_ISSUERS`, comma separated), be verified and carry
   the same e-mail; the second identity must not belong to anyone else. There is no automatic merge.
4. After a link, end the other (losing) account's sessions on its own app and disable it.

## Security checklist

- [ ] Pre-account-takeover: never link or merge on an e-mail address alone, and never on an
      unverified one. An attacker can pre-register a victim's address on the other app.
- [ ] Both-sides proof: each account proves control (verified token claims), from an issuer you
      trust. The link primitive refuses everything else.
- [ ] Session invalidation of the loser: end every session of the account that stops being used
      (`identity.end_sessions_of_user`) and disable it, so old tokens cannot reach merged data.
- [ ] `AUTH_TRUSTED_ISSUERS` lists only issuers you operate; empty means no linking.
- [ ] Analysis files and `kc.json` hold personal data (no hashes): store with 0600, delete after.
- [ ] The dual window is as short as possible and ends (maximum 90 days); expiry is checked on
      every request, from the generated config.
- [ ] Cut-over order: impact, export, Keycloak import, dual (explicit window), import + relink
      `--copy`, verify with real users, hub_only, remove `LEGACY_JWT_SECRET`.
- [ ] Code that reads `claims["sub"]` is moved to the `Principal` (`app.auth.deps.CurrentPrincipal`):
      under a hub the subject is not the local user id.
