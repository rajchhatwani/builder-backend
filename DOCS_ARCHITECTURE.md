# Documentation Architecture

**Status:** Active — this document governs the structure and maintenance of the Builder Backend documentation.  
**Created:** 2026-10-24  
**For:** Future documentation contributors, AI agents, and maintainers

---

## Philosophy & Framework

### Diátaxis Framework
We adopt the [Diátaxis documentation framework](https://diataxis.fr/), which organizes content into four distinct quadrants based on user intent:

```
                 Acquisition (learning)    Application (working)
              ┌──────────────────────────┬──────────────────────────┐
   Practical  │                          │                          │
   (doing)    │      TUTORIALS           │      HOW-TO GUIDES       │
              │   Learning-oriented      │   Goal-oriented          │
              │   "Take me by the hand"  │   "Show me how to..."    │
              │                          │                          │
              ├──────────────────────────┼──────────────────────────┤
              │                          │                          │
   Cognitive  │      EXPLANATION         │      REFERENCE           │
   (thinking) │   Understanding-oriented │   Information-oriented   │
              │   "Help me understand"   │   "Tell me the facts"    │
              │                          │                          │
              └──────────────────────────┴──────────────────────────┘
```

**Why Diátaxis?**
- Our platform is complex (auth, payments, storage, Keycloak, deployments, authz models)
- Users span experience levels: non-technical founders to senior DevOps engineers
- Clear separation prevents documentation becoming a "dense wall" or "scattered mess"
- Each quadrant serves a distinct user need at a distinct moment

### Progressive Disclosure
Documentation reveals complexity gradually:

1. **Landing/Overview** — 30-second pitch: what Builder Backend does
2. **Getting Started** — 5-minute quickstart (dashboard or API)
3. **Tutorials** — Guided learning paths (15-30 minutes each)
4. **How-To Guides** — Direct solutions to specific problems
5. **Reference** — Complete API documentation, exhaustive but scannable
6. **Explanation** — Deep dives into architecture, security, decisions

**Navigation principles:**
- Beginners start at Getting Started → Tutorials → select relevant How-To guides
- Experts jump directly to Reference or specific How-To guides via search
- Everyone uses Explanation when they need to understand *why* something works a certain way

---

## Documentation Framework: Docusaurus

**Selected:** Docusaurus v3  
**Rationale:**

| Requirement | Docusaurus | Alternatives |
|-------------|-----------|--------------|
| Versioning (docs by platform version) | ✅ Built-in | VitePress: manual, MkDocs: plugin |
| Search (critical for experts) | ✅ Algolia DocSearch (free) | All support, but Docusaurus integration is seamless |
| API Reference auto-generation | ✅ OpenAPI plugin | VitePress/MkDocs: require extra tooling |
| Custom domain (docs.mydomain.com) | ✅ GitHub Pages + CNAME | All support |
| Interactive elements (code tabs, collapsible sections) | ✅ MDX (React components) | VitePress: Vue, MkDocs: limited |
| AI/MCP consumption | ✅ Static HTML + llms.txt support | All support |
| Maintenance | ✅ Active (Meta-backed) | VitePress: newer, MkDocs: Python ecosystem |

**Trade-offs accepted:**
- Node.js dependency (vs. Python for MkDocs) — acceptable since frontend is already Node-based
- Heavier than VitePress — we need the features, not the lightest build

---

## Directory Structure

```
docs/                           # Docusaurus root
├── docs/                       # Main documentation content
│   ├── getting-started/
│   │   ├── overview.md         # What is Builder Backend?
│   │   ├── quickstart-dashboard.md
│   │   ├── quickstart-api.md
│   │   └── core-concepts.md    # Projects, entities, generations
│   │
│   ├── tutorials/              # Learning-oriented (step-by-step)
│   │   ├── build-your-first-api.md
│   │   ├── add-authentication.md
│   │   ├── add-payments.md
│   │   ├── add-file-uploads.md
│   │   ├── deploy-to-aws.md
│   │   └── keycloak-sso.md
│   │
│   ├── how-to/                 # Goal-oriented (problem-solving)
│   │   ├── data-model/
│   │   │   ├── create-entities-relations.md
│   │   │   ├── field-types-guide.md
│   │   │   └── modify-existing-model.md
│   │   ├── authentication/
│   │   │   ├── configure-smtp.md
│   │   │   ├── setup-sms-providers.md
│   │   │   ├── custom-registration-fields.md
│   │   │   ├── multi-tenancy.md
│   │   │   └── invite-only-signup.md
│   │   ├── authorization/
│   │   │   ├── choose-authz-model.md
│   │   │   ├── rbac-permissions.md
│   │   │   ├── abac-policies.md
│   │   │   └── pbac-policies.md
│   │   ├── keycloak/
│   │   │   ├── enable-keycloak.md
│   │   │   ├── configure-identity-providers.md
│   │   │   └── shared-realm-setup.md
│   │   ├── payments/
│   │   │   ├── setup-stripe.md
│   │   │   ├── setup-razorpay.md
│   │   │   ├── configure-refunds.md
│   │   │   └── sizing-calculator.md
│   │   ├── storage/
│   │   │   ├── setup-s3.md
│   │   │   ├── setup-minio.md
│   │   │   ├── configure-malware-scanning.md
│   │   │   └── file-field-type.md
│   │   ├── observability/
│   │   │   ├── enable-opentelemetry.md
│   │   │   ├── integrate-jaeger.md
│   │   │   └── sampling-strategies.md
│   │   ├── deployment/
│   │   │   ├── github-actions-setup.md
│   │   │   ├── deploy-aws.md
│   │   │   ├── deploy-azure.md
│   │   │   ├── deploy-gcp.md
│   │   │   └── custom-ci-cd.md
│   │   └── platform/
│   │       ├── manage-team-members.md
│   │       ├── api-tokens.md
│   │       └── admin-console.md
│   │
│   ├── reference/              # Information-oriented (technical specs)
│   │   ├── api/
│   │   │   ├── overview.md     # Authentication, errors, pagination
│   │   │   ├── account.md      # /account/* endpoints
│   │   │   ├── projects.md     # /projects/* endpoints
│   │   │   ├── entities.md
│   │   │   ├── fields.md
│   │   │   ├── relations.md
│   │   │   ├── auth.md         # /projects/{id}/auth
│   │   │   ├── keycloak.md
│   │   │   ├── payments.md
│   │   │   ├── storage.md
│   │   │   ├── authorization.md
│   │   │   ├── observability.md
│   │   │   ├── deployment.md
│   │   │   ├── generate.md
│   │   │   └── admin.md        # /admin/* (platform admins only)
│   │   ├── spec-schema.md      # Complete spec format
│   │   ├── generated-project/  # What you get in the zip
│   │   │   ├── structure.md
│   │   │   ├── environment-variables.md
│   │   │   ├── database-migrations.md
│   │   │   └── testing.md
│   │   ├── validation-errors.md # All validation codes & fixes
│   │   └── changelog.md        # Version history
│   │
│   ├── explanation/            # Understanding-oriented (concepts)
│   │   ├── architecture.md     # Builder vs generated project
│   │   ├── security-model.md   # Encryption, secrets, audit logs
│   │   ├── authorization-models.md  # RBAC vs ABAC vs PBAC deep dive
│   │   ├── multi-tenancy.md    # Shared schema, tenant isolation
│   │   ├── auth-providers.md   # Built-in vs Keycloak comparison
│   │   ├── payments-design.md  # Why a queue, safety guarantees
│   │   ├── storage-threat-model.md  # Security decisions
│   │   ├── observability-strategy.md  # Sampling, privacy
│   │   └── deployment-choices.md  # Why OIDC, no credentials
│   │
│   ├── faq.md                  # Common questions
│   └── troubleshooting.md      # Common issues + solutions
│
├── static/                     # Images, diagrams, downloadables
│   ├── img/
│   ├── diagrams/
│   └── postman/                # Postman collection (if distributing)
│
├── src/                        # Custom React components
│   ├── components/
│   │   ├── DashboardVsApi.tsx  # Feature matrix component
│   │   └── InteractiveDemo.tsx # Future: live playground
│   └── css/
│
├── versioned_docs/             # Auto-generated by Docusaurus
├── versioned_sidebars/
├── docusaurus.config.js
├── sidebars.js
├── package.json
└── llms.txt                    # AI agent index (see below)
```

---

## Content Guidelines

### For Each Content Type

#### Tutorials (Learning-Oriented)
- **Purpose:** Teach a beginner by *doing*
- **Structure:** Numbered steps, start to finish
- **Tone:** Patient, encouraging ("Let's build...", "You'll learn...")
- **Outcome:** A working example they can see/touch
- **Example:** "Build Your First API" — create a Blog project, add entities, generate, run locally

**Don't:**
- Explain every option (save for Reference)
- Offer choices ("you could also...") — pick one path
- Assume prior knowledge beyond the prerequisites

#### How-To Guides (Goal-Oriented)
- **Purpose:** Solve a specific problem
- **Structure:** Direct steps to achieve the goal
- **Tone:** Efficient, practical ("To configure X, do...")
- **Outcome:** The problem is solved
- **Example:** "Setup Multi-Tenancy" — exact steps, no theory

**Don't:**
- Teach concepts (link to Explanation instead)
- Include unrelated steps
- Start from scratch (link to prerequisites)

#### Reference (Information-Oriented)
- **Purpose:** Provide exhaustive, accurate facts
- **Structure:** Consistent format (endpoint → method → parameters → responses → examples)
- **Tone:** Neutral, precise, complete
- **Outcome:** User finds the exact detail they need
- **Example:** `POST /projects/{id}/auth` — every parameter, every error code, curl example

**Don't:**
- Explain *why* (that's Explanation)
- Provide tutorials or walkthroughs
- Omit edge cases or optional parameters

#### Explanation (Understanding-Oriented)
- **Purpose:** Deepen understanding of *why* and *how it works*
- **Structure:** Narrative, diagrams, comparisons
- **Tone:** Thoughtful, exploratory ("We chose X because...")
- **Outcome:** User understands the design, can make informed decisions
- **Example:** "Authorization Models Compared" — RBAC vs ABAC vs PBAC, when to use each, trade-offs

**Don't:**
- Give step-by-step instructions (that's Tutorials/How-To)
- Just list facts (that's Reference)

---

## Dashboard vs. API

**Key principle:** Clearly document which features are available where.

| Feature | Dashboard | API | Notes |
|---------|-----------|-----|-------|
| Create project | ✅ | ✅ | Both |
| Edit entities/fields | ✅ | ✅ | Both, API more powerful for bulk |
| Configure auth | ✅ | ✅ | Dashboard = forms, API = full control |
| Manage roles/permissions | ✅ | ✅ | Dashboard has visual coverage matrix |
| Authorization policies (ABAC/PBAC) | ✅ | ✅ | Dashboard has policy editor + simulator |
| Generate/download zip | ✅ | ✅ | Both |
| API tokens | ✅ | ❌ | Dashboard only (requires session) |
| Admin console | ✅ | ✅ | Both (separate auth) |
| Postman collection | — | ✅ | API testing aid |

**Documentation strategy:**
- Getting Started: offer both paths (dashboard = visual, API = automation)
- Tutorials: use dashboard for learning (lower barrier)
- How-To: show both when relevant, prefer API examples for reproducibility
- Reference: API only (exhaustive endpoint docs)

---

## Versioning Strategy

**Versioning scheme:** Matches platform releases (e.g., `v1.0`, `v1.1`, `v2.0`)

**When to create a new version:**
- Breaking API changes
- Major feature additions that change the mental model (e.g., adding ABAC/PBAC)
- Generated project format changes

**How to version:**
```bash
npm run docusaurus docs:version 1.0
```

**Maintenance:**
- Latest version (`/docs`) is always current
- Previous versions archived (`/versioned_docs/version-1.0`)
- Security fixes backported to last 2 major versions
- Deprecation warnings added 2 versions before removal

**Version banner:** "You're viewing docs for v1.0. Latest is v2.0 [switch →]"

---

## Search & Discoverability

### Algolia DocSearch (Free Tier)
- Submit to [DocSearch program](https://docsearch.algolia.com/apply/)
- Requirements: public docs, open-source or free tier
- Configuration in `docusaurus.config.js`

### Alternative (if needed): Local Search
- Plugin: `@easyops-cn/docusaurus-search-local`
- Trade-off: slower, less accurate, but no external dependency

### SEO Metadata
Every doc must have:
```markdown
---
title: "Setup Multi-Tenancy"
description: "Enable multi-tenancy to isolate customer data by organization"
keywords: [multi-tenancy, saas, tenant, isolation]
---
```

---

## AI Agent & MCP Optimization

### llms.txt
A machine-readable index at the root (`/llms.txt`):

```
# Builder Backend Documentation
# Provider: Builder Backend (docs.mydomain.com)
# Last Updated: 2026-10-24

## Core Documentation
- Getting Started: /docs/getting-started/overview
- API Reference: /docs/reference/api/overview
- Tutorials: /docs/tutorials/

## Feature-Specific
- Authentication: /docs/how-to/authentication/
- Authorization (RBAC/ABAC/PBAC): /docs/explanation/authorization-models
- Payments: /docs/how-to/payments/
- File Uploads: /docs/how-to/storage/
- Keycloak SSO: /docs/how-to/keycloak/
- Deployment: /docs/how-to/deployment/

## Troubleshooting
- FAQ: /docs/faq
- Common Issues: /docs/troubleshooting
- Validation Errors: /docs/reference/validation-errors

## API Endpoints Summary
See full reference: /docs/reference/api/overview
- Authentication: POST /account/register, /login
- Projects: GET/POST /projects, GET/PATCH /projects/{id}
- Spec: GET/PUT /projects/{id}/spec, POST /projects/{id}/validate
- Generate: POST /projects/{id}/generate/preview, GET .../download
```

### Structured Metadata
Each major section includes:
```markdown
<!-- AI Context Boundary -->
**For AI agents:** This section covers [authentication configuration].
Prerequisites: [project created, builder account].
Related: [authorization models], [Keycloak integration].
Common tasks: [enable email/SMS], [setup SMTP], [configure multi-tenancy].
```

### Code Examples
- Every API endpoint has a curl example
- Complex flows have SDK examples (when available)
- All examples are copy-pasteable and use placeholder values like `YOUR_TOKEN`, `PROJECT_ID`

---

## Maintenance Principles

### Consistency
- Use the same terms everywhere (e.g., "generated project" not "downloaded API" or "output backend")
- Cross-reference liberally (Tutorials → Reference, How-To → Explanation)
- Keep sidebars synchronized with actual file structure

### Updating Content
**When code changes:**
1. Update Reference first (source of truth)
2. Check if Tutorials/How-To need updates
3. Add to Changelog
4. If breaking: version the docs

**When adding features:**
1. Write Reference documentation
2. Add How-To guide for the happy path
3. Add Explanation if it's architecturally significant
4. Update feature matrix (Dashboard vs API)
5. Update llms.txt

**When fixing bugs:**
- Update Troubleshooting if user-facing
- Update Validation Errors if relevant

### Review Checklist
Before publishing:
- [ ] Correct Diátaxis quadrant?
- [ ] Links work?
- [ ] Code examples tested?
- [ ] SEO metadata present?
- [ ] Consistent terminology?
- [ ] Prerequisites stated?
- [ ] Related docs linked?

---

## Deployment

### Cloudflare Pages (Recommended)
Cloudflare Pages works with **private repositories** and provides:
- Automatic deployments on push
- Preview deployments for pull requests
- Custom domains with automatic HTTPS
- Global CDN (fast worldwide)
- Unlimited bandwidth (free tier)

**Setup Steps:**

1. **Create Cloudflare Pages Project**
   - Go to [Cloudflare Dashboard](https://dash.cloudflare.com/) → Pages
   - Click "Create a project"
   - Connect your Git repository (GitHub, GitLab, or direct Git)
   - Or use Direct Upload method with GitHub Actions

2. **Configure Build Settings** (if using Cloudflare's Git integration)
   - Build command: `cd docs && npm ci && npm run build`
   - Build output directory: `docs/build`
   - Root directory: `/`
   - Node version: `20`

3. **GitHub Actions Deployment** (recommended for private repos)
   
   Add these secrets to your GitHub repository:
   - `CLOUDFLARE_API_TOKEN` - Create at [Cloudflare API Tokens](https://dash.cloudflare.com/profile/api-tokens)
     - Use "Edit Cloudflare Workers" template
     - Permissions: Account > Cloudflare Pages > Edit
   - `CLOUDFLARE_ACCOUNT_ID` - Found in Cloudflare dashboard URL

   The workflow at `.github/workflows/deploy-docs.yml` handles deployment automatically.

4. **Custom Domain**
   - In Cloudflare Pages project → Settings → Custom domains
   - Add `docs.mydomain.com`
   - If domain is on Cloudflare: DNS configured automatically
   - If domain elsewhere: Add CNAME record: `docs` → `<project>.pages.dev`
   - HTTPS certificate provisioned automatically

**Deployment URL:**
- Production: `https://<project-name>.pages.dev` or `https://docs.mydomain.com`
- Preview: `https://<commit-hash>.<project-name>.pages.dev` (automatic on PRs)

**GitHub Action (`.github/workflows/deploy-docs.yml`):**
```yaml
name: Deploy Documentation to Cloudflare Pages
on:
  push:
    branches: [main]
    paths: ['docs/**']
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
          cache-dependency-path: docs/package-lock.json
      - run: npm ci
        working-directory: docs
      - run: npm run build
        working-directory: docs
      - uses: cloudflare/wrangler-action@v3
        with:
          apiToken: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          accountId: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
          command: pages deploy docs/build --project-name=builder-backend-docs --branch=main
```

### Alternative: GitHub Pages (Public Repos Only)
If your repository is public, you can use GitHub Pages:
1. Enable in repo Settings → Pages
2. Source: Deploy from a branch → `gh-pages`
3. Custom domain: `docs.mydomain.com`
4. Add CNAME record in DNS: `docs` → `<your-org>.github.io`

**Note:** GitHub Pages doesn't work well with private repositories (limited collaborators).

### Local Preview
Test the production build locally:
```bash
cd docs
npm run build
npm run serve
```

---

## Future Enhancements

### Planned (Not Yet Implemented)
- **Interactive API playground** (try endpoints with your token)
- **Community examples repository** (link from docs, curated)
- **Video tutorials** (embed in relevant Tutorials)
- **Localization** (i18n for non-English markets)
- **MCP Server** (structured protocol for AI agent access)

### Coming Soon Placeholders
Where features are planned but not ready:
```markdown
> **Coming Soon:** Community forum for sharing examples and patterns.
```

---

## Questions for Future Contributors

**Unsure which quadrant?**
- Does the user want to learn by doing? → Tutorial
- Do they have a specific goal? → How-To
- Do they need a fact? → Reference
- Do they need to understand *why*? → Explanation

**Unsure if Dashboard or API?**
- Check the feature matrix (above)
- When in doubt, document both with preference noted

**Unsure about versioning?**
- If it's a fix/clarification → update current docs
- If it's a breaking change → version the docs

**Need help?**
- Re-read this document
- Check similar existing documentation for patterns
- Consult the Diátaxis website: https://diataxis.fr/

---

**This is a living document.** Update it when documentation strategy changes.
