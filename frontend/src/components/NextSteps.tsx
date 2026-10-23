import type { AuthConfig } from '../api/types'

interface NextStepsProps {
  slug: string
  /** The project's auth settings, or null when it has none. */
  auth: AuthConfig | null
}

interface EnvVar {
  name: string
  why: string
  how: string
}

const DOCKER_KEY_COMMAND =
  'docker run --rm -v "$PWD":/srv -w /srv python:3.12-slim sh -c "pip install -q cryptography && python -m app.auth.keys"'

/** The environment variables the generated project reads, derived from the auth settings. */
export function requiredEnvVars(auth: AuthConfig | null): EnvVar[] {
  if (auth === null || !auth.enabled) return []
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
export function NextSteps({ slug, auth }: NextStepsProps) {
  const vars = requiredEnvVars(auth)
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
