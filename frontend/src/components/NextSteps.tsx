import type { AuthConfig, KeycloakConfig } from '../api/types'
import { secretEnvName } from './KeycloakPanel'

interface NextStepsProps {
  slug: string
  /** The project's auth settings, or null when it has none. */
  auth: AuthConfig | null
  /** The Keycloak settings, when the project uses Keycloak. */
  keycloak?: KeycloakConfig | null
}

interface EnvVar {
  name: string
  why: string
  how: string
}

const DOCKER_KEY_COMMAND =
  'docker run --rm -v "$PWD":/srv -w /srv python:3.12-slim sh -c "pip install -q cryptography && python -m app.auth.keys"'

/** The environment variables a Keycloak project needs (nothing secret is ever in the zip). */
function keycloakEnvVars(auth: AuthConfig, keycloak: KeycloakConfig): EnvVar[] {
  const own = keycloak.mode === 'own'
  const vars: EnvVar[] = [
    {
      name: 'KEYCLOAK_PUBLIC_URL',
      why: 'The address people reach Keycloak at. Tokens are only accepted from exactly this address',
      how: own
        ? 'http://localhost:8081 for local work; your real https address in production'
        : 'The address of your existing Keycloak',
    },
    {
      name: 'API_PUBLIC_URL',
      why: 'Where this API is reachable (Swagger UI signs in and returns here)',
      how: 'http://localhost:8000 for local work',
    },
  ]
  if (own) {
    vars.push(
      { name: 'KEYCLOAK_DB_PASSWORD', why: "Password of Keycloak's own database", how: 'Make up a long random one' },
      {
        name: 'KC_BOOTSTRAP_ADMIN_USERNAME / KC_BOOTSTRAP_ADMIN_PASSWORD',
        why: 'The first Keycloak admin, used once',
        how: 'Make them up, then create your own admin in the console and delete this one',
      },
    )
    if (auth.smtp_config) {
      vars.push(
        { name: 'SMTP_USERNAME', why: `Login for ${auth.smtp_config.host}:${auth.smtp_config.port} (Keycloak sends the emails)`, how: 'From your email provider' },
        { name: 'SMTP_PASSWORD', why: 'Password or API key for that login', how: 'From your email provider' },
      )
    }
    for (const idp of keycloak.identity_providers) {
      vars.push({
        name: secretEnvName(idp.alias),
        why: `Client secret of the ${idp.display_name || idp.alias} login`,
        how: "From the provider's console, where you registered your app",
      })
    }
  } else {
    vars.push({
      name: 'KEYCLOAK_ADMIN_USERNAME / KEYCLOAK_ADMIN_PASSWORD',
      why: "An admin of the existing Keycloak, only for the one-time registration script",
      how: 'Your Keycloak administrator',
    })
  }
  return vars
}

/** The environment variables the generated project reads, derived from the auth settings. */
export function requiredEnvVars(auth: AuthConfig | null, keycloak: KeycloakConfig | null = null): EnvVar[] {
  if (auth === null || !auth.enabled) return []
  if (auth.provider === 'keycloak' && keycloak !== null) return keycloakEnvVars(auth, keycloak)
  const vars: EnvVar[] = []
  if (auth.jwt_algorithm === 'RS256') {
    vars.push({
      name: 'AUTH_JWT_PRIVATE_KEY',
      why: 'RSA key that signs access tokens',
      how: `Generate one: ${DOCKER_KEY_COMMAND}`,
    })
  } else {
    vars.push({
      name: 'AUTH_JWT_SECRET',
      why: 'Signs access tokens (32+ characters)',
      how: 'Generate one: python3 -m app.auth.keys',
    })
  }
  if (auth.smtp_config) {
    vars.push(
      {
        name: 'SMTP_USERNAME',
        why: `Login for ${auth.smtp_config.host}:${auth.smtp_config.port}`,
        how: 'From your email provider (may be blank for servers without login)',
      },
      { name: 'SMTP_PASSWORD', why: 'Password or API key for that login', how: 'From your email provider' },
    )
  }
  if (auth.sms_provider && auth.sms_config) {
    if (auth.sms_provider === 'twilio') {
      vars.push(
        { name: 'TWILIO_ACCOUNT_SID', why: 'Twilio account', how: 'Twilio console' },
        { name: 'TWILIO_AUTH_TOKEN', why: 'Twilio credential', how: 'Twilio console' },
      )
    } else if (auth.sms_provider === 'vonage') {
      vars.push(
        { name: 'VONAGE_API_KEY', why: 'Vonage account', how: 'Vonage dashboard' },
        { name: 'VONAGE_API_SECRET', why: 'Vonage credential', how: 'Vonage dashboard' },
      )
    } else {
      vars.push(
        { name: 'AWS_REGION', why: 'Region SNS sends from', how: 'e.g. eu-west-1' },
        {
          name: 'AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY',
          why: 'AWS credentials (or use an instance role)',
          how: 'AWS IAM',
        },
      )
    }
  }
  if (auth.token_store === 'redis') {
    vars.push({
      name: 'REDIS_URL',
      why: 'Where refresh tokens are kept',
      how: 'Already set by docker compose; set it yourself if you run without compose',
    })
  }
  return vars
}

/** Shown after a download: what to do with the zip, and where the secrets come from. */
export function NextSteps({ slug, auth, keycloak = null }: NextStepsProps) {
  const vars = requiredEnvVars(auth, keycloak)
  if (auth !== null && auth.enabled && auth.provider === 'keycloak' && keycloak !== null) {
    return <KeycloakNextSteps slug={slug} keycloak={keycloak} vars={vars} />
  }
  return (
    <div className="card" style={{ marginBlockEnd: 'var(--space-6)' }}>
      <h4>Before you run {slug}</h4>
      <ol>
        <li>
          Unzip it and copy the example settings: <code>cp .env.example .env</code>
        </li>
        {vars.length > 0 && (
          <li>
            Fill in the secrets below in <code>.env</code>. <strong>The zip contains no secrets</strong>:
            credentials you enter here or in the Authentication section never leave this server.
          </li>
        )}
        <li>
          Start it: <code>docker compose up --build</code>, then open{' '}
          <code>http://localhost:8000/docs</code>
        </li>
        <li>
          Run its tests: <code>make test</code>
        </li>
      </ol>
      {vars.length > 0 && (
        <div className="table">
          <table>
            <thead>
              <tr>
                <th>Variable</th>
                <th>What it is</th>
                <th>Where it comes from</th>
              </tr>
            </thead>
            <tbody>
              {vars.map((v) => (
                <tr key={v.name}>
                  <td>
                    <code>{v.name}</code>
                  </td>
                  <td>{v.why}</td>
                  <td>{v.how}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {vars.length > 0 && (
        <p style={{ color: 'var(--muted-foreground)' }}>
          Everything that is not a secret (SMTP host and sender, token lifetimes, roles, rate limits)
          is already in <code>app/auth/config.py</code>. Rate limits are counted per worker.
        </p>
      )}
    </div>
  )
}

function VarTable({ vars }: { vars: EnvVar[] }) {
  return (
    <div className="table">
      <table>
        <thead>
          <tr>
            <th>Variable</th>
            <th>What it is</th>
            <th>Where it comes from</th>
          </tr>
        </thead>
        <tbody>
          {vars.map((v) => (
            <tr key={v.name}>
              <td>
                <code>{v.name}</code>
              </td>
              <td>{v.why}</td>
              <td>{v.how}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Shown after a download of a project that signs in through Keycloak. */
function KeycloakNextSteps({ slug, keycloak, vars }: { slug: string; keycloak: KeycloakConfig; vars: EnvVar[] }) {
  const own = keycloak.mode === 'own'
  return (
    <div className="card" style={{ marginBlockEnd: 'var(--space-6)' }}>
      <h4>Before you run {slug}</h4>
      <ol>
        <li>
          Unzip it and copy the example settings: <code>cp .env.example .env</code>, then fill in the values below.{' '}
          <strong>The zip contains no secrets.</strong>
        </li>
        {own ? (
          <>
            <li>
              Start it: <code>docker compose up --build</code>. Keycloak takes about a minute, then the API follows.
            </li>
            <li>
              Open the Keycloak admin console (<code>http://localhost:8081/admin</code>), sign in as the first admin, create
              your own admin account and delete the first one.
            </li>
            <li>
              In the <code>{keycloak.realm}</code> realm, create your users and give them roles on the{' '}
              <code>{keycloak.api_client_id}</code> client. Then open <code>http://localhost:8000/docs</code>, press{' '}
              <strong>Authorize</strong> and sign in.
            </li>
          </>
        ) : (
          <>
            <li>
              Register this project in your Keycloak once:{' '}
              <code>python scripts/keycloak_register.py</code> (it adds the clients and roles, and can be run again).
            </li>
            <li>
              Start it: <code>docker compose up --build</code>, then give your users roles on the{' '}
              <code>{keycloak.api_client_id}</code> client in Keycloak.
            </li>
          </>
        )}
        <li>
          Run its tests: <code>make test</code> (they need no Keycloak).
        </li>
      </ol>
      <VarTable vars={vars} />
    </div>
  )
}
