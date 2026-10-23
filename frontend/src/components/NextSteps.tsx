import type { AuthConfig, KeycloakConfig, PaymentsConfig, StorageConfig } from '../api/types'
import { secretEnvName } from './KeycloakPanel'

interface NextStepsProps {
  slug: string
  /** The project's auth settings, or null when it has none. */
  auth: AuthConfig | null
  /** The Keycloak settings, when the project uses Keycloak. */
  keycloak?: KeycloakConfig | null
  /** The payments settings, when payments are switched on. */
  payments?: PaymentsConfig | null
  /** The storage settings, when file uploads are switched on. */
  storage?: StorageConfig | null
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
export function NextSteps({ slug, auth, keycloak = null, payments = null, storage = null }: NextStepsProps) {
  return (
    <>
      <AuthNextSteps slug={slug} auth={auth} keycloak={keycloak} />
      {payments !== null && <PaymentsNextSteps slug={slug} payments={payments} />}
      {storage !== null && <StorageNextSteps slug={slug} storage={storage} />}
    </>
  )
}

function AuthNextSteps({ slug, auth, keycloak }: { slug: string; auth: AuthConfig | null; keycloak: KeycloakConfig | null }) {
  const vars = requiredEnvVars(auth, keycloak)
  if (auth !== null && auth.enabled && auth.provider === 'keycloak' && keycloak !== null) {
    return <KeycloakNextSteps slug={slug} keycloak={keycloak} vars={vars} multiTenant={auth.multi_tenant} />
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
function KeycloakNextSteps({ slug, keycloak, vars, multiTenant }: { slug: string; keycloak: KeycloakConfig; vars: EnvVar[]; multiTenant: boolean }) {
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
              <code>{keycloak.api_client_id}</code> client.{' '}
              {multiTenant && 'Create organizations and add each user to one: each organization is a tenant. '} Then open <code>http://localhost:8000/docs</code>, press{' '}
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

const PROVIDER_ENV: Record<PaymentsConfig['provider'], { title: string; vars: EnvVar[]; events: string[] }> = {
  stripe: {
    title: 'Stripe',
    vars: [
      {
        name: 'STRIPE_SECRET_KEY',
        why: 'Your Stripe API key. A test key (sk_test_...) until you go live; a live key only works with APP_ENV=production',
        how: 'Stripe dashboard → Developers → API keys',
      },
      {
        name: 'STRIPE_WEBHOOK_SECRETS',
        why: 'Signing secret of the webhook endpoint (whsec_...). List two, comma separated, while rotating',
        how: 'Stripe dashboard → Developers → Webhooks, after adding the endpoint below',
      },
    ],
    events: [
      'checkout.session.completed',
      'checkout.session.async_payment_succeeded',
      'checkout.session.async_payment_failed',
      'checkout.session.expired',
      'charge.refunded',
      'refund.created',
      'refund.updated',
      'charge.refund.updated',
      'charge.dispute.created',
      'charge.dispute.updated',
      'charge.dispute.closed',
    ],
  },
  razorpay: {
    title: 'Razorpay',
    vars: [
      { name: 'RAZORPAY_KEY_ID', why: 'Your Razorpay key id (rzp_test_... until you go live)', how: 'Razorpay dashboard → Account & Settings → API keys' },
      { name: 'RAZORPAY_KEY_SECRET', why: 'The secret that goes with that key id', how: 'Shown once when you create the key' },
      {
        name: 'RAZORPAY_WEBHOOK_SECRETS',
        why: 'The secret you type when creating the webhook (16+ characters). List two, comma separated, while rotating',
        how: 'You choose it: make it long and random',
      },
    ],
    events: [
      'payment_link.paid',
      'payment_link.expired',
      'payment_link.cancelled',
      'refund.created',
      'refund.processed',
      'refund.failed',
      'payment.dispute.created',
      'payment.dispute.won',
      'payment.dispute.lost',
      'payment.dispute.closed',
      'payment.dispute.under_review',
      'payment.dispute.action_required',
    ],
  },
}

/** Shown after a download of a project with payments switched on. */
function PaymentsNextSteps({ slug, payments }: { slug: string; payments: PaymentsConfig }) {
  const info = PROVIDER_ENV[payments.provider]
  const vars: EnvVar[] = [
    ...info.vars,
    ...(payments.security.webhook_ip_allowlist_enabled
      ? [{ name: 'PAYMENTS_WEBHOOK_IP_ALLOWLIST', why: 'The addresses the provider calls from (comma-separated CIDRs). Required, because you switched the allowlist on', how: `${info.title} documentation` }]
      : []),
    { name: 'APP_ENV', why: 'Set to production in production. A live key anywhere else, or a test key in production, stops the app from starting', how: 'You set it' },
  ]
  return (
    <div className="card" style={{ marginBlockEnd: 'var(--space-6)' }}>
      <h4>Payments: before you run {slug}</h4>
      <ol>
        <li>
          Put the settings below in <code>.env</code>. <strong>No key is ever in the zip</strong> and none is stored in this
          dashboard.
        </li>
        <li>
          In {info.title}, add a webhook to <code>https://&lt;your-api&gt;/payments/webhooks/{payments.provider}</code> and select
          exactly these events: {info.events.map((e, i) => (
            <span key={e}>
              <code>{e}</code>
              {i < info.events.length - 1 ? ', ' : '.'}
            </span>
          ))}
        </li>
        <li>
          Start it with <code>docker compose up --build</code>: besides the API it starts <code>payments-worker</code>, which has
          to keep running.
        </li>
        <li>
          Read <code>deploy/DEPLOYMENT.md</code> in the zip: it has the sizing worked out for your load, how to run workers on
          other servers, the database login script, going from test to live, and what to do when something is stuck.
        </li>
      </ol>
      <VarTable vars={vars} />
      <p style={{ color: 'var(--muted-foreground)' }}>
        The sizing numbers are estimates, not measurements: load-test them before relying on them.
      </p>
    </div>
  )
}

/** Shown after a download of a project with file uploads switched on. */
function StorageNextSteps({ slug, storage }: { slug: string; storage: StorageConfig }) {
  const minio = storage.backend === 'minio'
  const vars: EnvVar[] = minio
    ? [
        {
          name: 'STORAGE_ACCESS_KEY_ID',
          why: 'The login of your S3-compatible server. docker compose also uses it as the admin login of the local development store',
          how: 'You choose it (a long random value)',
        },
        {
          name: 'STORAGE_SECRET_ACCESS_KEY',
          why: 'The password that goes with it',
          how: 'You choose it (a long random value)',
        },
        {
          name: 'STORAGE_ENDPOINT_URL',
          why: 'The S3 address of your server. Must be https:// in production',
          how: 'Already set for local work (http://objectstore:8333)',
        },
      ]
    : [
        {
          name: 'STORAGE_ACCESS_KEY_ID / STORAGE_SECRET_ACCESS_KEY',
          why: 'Credentials for the bucket. On AWS leave them empty and give the service an IAM role instead',
          how: 'AWS IAM: use the policy in deploy/storage/iam-policy.json',
        },
        { name: 'STORAGE_REGION', why: 'The AWS region of the bucket', how: storage.region ?? 'Your bucket region' },
      ]
  vars.push({
    name: 'APP_ENV',
    why: 'Set to production in production. It then refuses plain-http storage addresses and development shortcuts',
    how: 'You set it',
  })
  return (
    <div className="card" style={{ marginBlockEnd: 'var(--space-6)' }}>
      <h4>File uploads: before you run {slug}</h4>
      <ol>
        <li>
          Put the settings below in <code>.env</code>. <strong>No credential is ever in the zip</strong> and none is stored in this
          dashboard.
        </li>
        {!minio && (
          <li>
            Create the bucket <code>{storage.bucket}</code> with the commands in <code>deploy/storage/STORAGE.md</code> (block public
            access, encryption, versioning, the policy files next to it). The app never creates buckets in production.
          </li>
        )}
        {minio && (
          <li>
            <code>docker compose up --build</code> starts a local S3-compatible store for development. For real use point{' '}
            <code>STORAGE_ENDPOINT_URL</code> at your own server. (MinIO's community edition no longer publishes images, so the local
            store is SeaweedFS; any S3-compatible server works.)
          </li>
        )}
        <li>
          Start it with <code>docker compose up --build</code>: it also starts <code>clamav</code>, the malware scanner. It needs
          about 1.5 GB of memory and a few minutes on first start to download its signatures; until then uploads are refused, never
          let through unscanned.
        </li>
        <li>
          Run <code>make storage-maintenance</code> every hour (cron) and with <code>--rescan</code> daily: it cleans up after crashes,
          finishes deletions, rescans old files and logs the audit digest to keep somewhere safe.
        </li>
        <li>
          Read <code>deploy/storage/STORAGE.md</code> (setup, operations, erasure requests) and <code>docs/storage-security.md</code>{' '}
          (the threat model) in the zip.
        </li>
      </ol>
      <VarTable vars={vars} />
    </div>
  )
}
