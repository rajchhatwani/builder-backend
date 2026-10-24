# Continuous integration for @@PROJECT@@ (generated). Runs on every pull request and every push to main.
# Nothing here has cloud access: deployment is a separate workflow (deploy.yml) with its own permissions.
name: CI

on:
  pull_request:
  push:
    branches: [main]

# The default token can read the repository and nothing else. Jobs that need more say so themselves.
permissions:
  contents: read

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  test:
    name: Lint and test
    runs-on: ubuntu-24.04
    timeout-minutes: 20
    services:
      postgres:
        image: @@POSTGRES_IMAGE@@
        env:
          POSTGRES_USER: app
          POSTGRES_PASSWORD: app
          POSTGRES_DB: app
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U app -d app"
          --health-interval 3s
          --health-timeout 3s
          --health-retries 20
    env:
      DATABASE_URL: postgresql+asyncpg://app:app@localhost:5432/app_test
    steps:
      - uses: @@pin:actions/checkout@@
        with:
          persist-credentials: false
      - uses: @@pin:actions/setup-python@@
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: |
            requirements.txt
            requirements-dev.txt
      - name: Install dependencies
        run: pip install -r requirements.txt -r requirements-dev.txt
      - name: Lint
        run: ruff check .
      - name: Prepare the test database and apply migrations
        run: |
          python -m tests._prepare_db
          alembic upgrade head
          # The models and the migrations must describe the same schema.
          alembic check
      - name: Test
        run: pytest -q

  image:
    name: Build image, scan, SBOM
    needs: test
    runs-on: ubuntu-24.04
    timeout-minutes: 20
    steps:
      - uses: @@pin:actions/checkout@@
        with:
          persist-credentials: false
      - uses: @@pin:docker/setup-buildx-action@@
      - name: Build the image (not pushed)
        uses: @@pin:docker/build-push-action@@
        with:
          context: .
          load: true
          push: false
          tags: @@SLUG@@:ci
          cache-from: type=gha
          cache-to: type=gha,mode=max
      # Fails the build on a fixable HIGH or CRITICAL vulnerability in the OS packages or Python
      # dependencies. Vulnerabilities with no fix yet are reported by the scanner but do not block.
      - name: Scan the image for vulnerabilities
        uses: @@pin:aquasecurity/trivy-action@@
        with:
          image-ref: @@SLUG@@:ci
          format: table
          severity: CRITICAL,HIGH
          ignore-unfixed: true
          exit-code: "1"
      - name: Software bill of materials
        uses: @@pin:anchore/sbom-action@@
        with:
          image: @@SLUG@@:ci
          format: cyclonedx-json
          output-file: sbom.cdx.json
          upload-artifact: false
      - uses: @@pin:actions/upload-artifact@@
        with:
          name: sbom
          path: sbom.cdx.json
          retention-days: 90

  terraform:
    name: Terraform format and validate
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    steps:
      - uses: @@pin:actions/checkout@@
        with:
          persist-credentials: false
      - uses: @@pin:hashicorp/setup-terraform@@
        with:
          terraform_version: @@TERRAFORM_VERSION@@
          terraform_wrapper: false
      - name: Format
        run: terraform fmt -check -recursive deploy/@@CLOUD@@
      - name: Validate the stack and the one-time bootstrap
        run: |
          for dir in deploy/@@CLOUD@@ deploy/@@CLOUD@@/bootstrap; do
            terraform -chdir="$dir" init -backend=false -input=false
            terraform -chdir="$dir" validate
          done
