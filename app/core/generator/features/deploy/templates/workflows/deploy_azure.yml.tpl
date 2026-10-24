# Deployment of @@PROJECT@@ to Azure (generated).
#
#   push to main            -> build once, deploy to @@FIRST_ENV@@
#   Actions > Deploy > Run  -> choose an environment (and an image tag that is already built) to promote
#
# Signs in with a federated credential (GitHub's short-lived OIDC token): there is no client secret
# anywhere. Each GitHub environment (@@ENV_LIST@@) has its own Entra application (variable AZURE_CLIENT_ID), so
# production can require reviewers in Settings > Environments. One-time setup: docs/DEPLOYMENT.md.
name: Deploy

on:
  push:
    branches: [main]
  workflow_dispatch:
    inputs:
      environment:
        description: Where to deploy
        type: choice
        options: [@@ENV_OPTIONS@@]
        default: @@FIRST_ENV@@
      image_tag:
        description: Image tag to promote (empty builds the current commit)
        type: string
        default: ""

permissions:
  contents: read

concurrency:
  group: deploy-${{ inputs.environment || '@@FIRST_ENV@@' }}
  cancel-in-progress: false # never stop a deployment half way

jobs:
  deploy:
    runs-on: ubuntu-24.04
    timeout-minutes: 60
    environment: ${{ inputs.environment || '@@FIRST_ENV@@' }}
    permissions:
      contents: read
      id-token: write # the OIDC token, for Azure and for signing the image
    env:
      TARGET: ${{ inputs.environment || '@@FIRST_ENV@@' }}
      ARM_USE_OIDC: "true"
      ARM_CLIENT_ID: ${{ vars.AZURE_CLIENT_ID }}
      ARM_TENANT_ID: ${{ vars.AZURE_TENANT_ID }}
      ARM_SUBSCRIPTION_ID: ${{ vars.AZURE_SUBSCRIPTION_ID }}
      REGISTRY_NAME: ${{ vars.ACR_NAME }}
      REGISTRY_RG: ${{ vars.TF_STATE_RESOURCE_GROUP }}
      TF_STATE_ACCOUNT: ${{ vars.TF_STATE_STORAGE_ACCOUNT }}
      TF_STATE_RESOURCE_GROUP: ${{ vars.TF_STATE_RESOURCE_GROUP }}
      IMAGE_TAG: ${{ inputs.image_tag || github.sha }}
    steps:
      - uses: @@pin:actions/checkout@@
        with:
          persist-credentials: false

      - name: Sign in to Azure (OIDC)
        uses: @@pin:azure/login@@
        with:
          client-id: ${{ vars.AZURE_CLIENT_ID }}
          tenant-id: ${{ vars.AZURE_TENANT_ID }}
          subscription-id: ${{ vars.AZURE_SUBSCRIPTION_ID }}

      - name: Sign in to the registry
        run: az acr login --name "$REGISTRY_NAME"

      - uses: @@pin:docker/setup-buildx-action@@

      - name: Build and push the image (skipped when promoting an existing tag)
        id: build
        if: ${{ inputs.image_tag == '' }}
        uses: @@pin:docker/build-push-action@@
        with:
          context: .
          push: true
          tags: ${{ vars.ACR_NAME }}.azurecr.io/@@SLUG@@:${{ env.IMAGE_TAG }}
          provenance: mode=max
          sbom: true
          cache-from: type=gha
          cache-to: type=gha,mode=max

      - name: Make sure the image exists
        run: az acr repository show --name "$REGISTRY_NAME" --image "@@SLUG@@:${IMAGE_TAG}" --query digest -o tsv

      - name: Sign the image (keyless, recorded in the public transparency log)
        if: ${{ inputs.image_tag == '' }}
        uses: @@pin:sigstore/cosign-installer@@
      - if: ${{ inputs.image_tag == '' }}
        run: cosign sign --yes "${REGISTRY_NAME}.azurecr.io/@@SLUG@@@${{ steps.build.outputs.digest }}"

      - uses: @@pin:hashicorp/setup-terraform@@
        with:
          terraform_version: @@TERRAFORM_VERSION@@
          terraform_wrapper: false

      - name: Terraform init
        working-directory: deploy/azure
        run: |
          terraform init -input=false \
            -backend-config="resource_group_name=${TF_STATE_RESOURCE_GROUP}" \
            -backend-config="storage_account_name=${TF_STATE_ACCOUNT}" \
            -backend-config="container_name=tfstate" \
            -backend-config="key=@@SLUG@@/${TARGET}.tfstate" \
            -backend-config="use_oidc=true" \
            -backend-config="use_azuread_auth=true"

      # Step 1: make sure the infrastructure exists and is current while the service keeps running the
      # image it already has (the first deployment has none, so it starts from the new one).
      - name: Terraform apply (infrastructure, service unchanged)
        working-directory: deploy/azure
        run: |
          IMAGE="${REGISTRY_NAME}.azurecr.io/@@SLUG@@:${IMAGE_TAG}"
          CURRENT="$(terraform output -raw deployed_image 2>/dev/null || true)"
          terraform apply -input=false -auto-approve -var-file="environments/${TARGET}.tfvars" \
            -var "subscription_id=${ARM_SUBSCRIPTION_ID}" -var "registry_name=${REGISTRY_NAME}" \
            -var "registry_resource_group=${REGISTRY_RG}" -var "image=${CURRENT:-$IMAGE}"

      # Terraform creates each secret with a placeholder; a person must replace it. Deploying with a
      # placeholder would start the service with a meaningless secret, so stop here instead.
      - name: Check that every secret has been set
        working-directory: deploy/azure
        run: |
          VAULT="$(terraform output -raw key_vault)"
          STATUS=0
          for NAME in $(terraform output -json secrets_to_fill | jq -r '.[]'); do
            VALUE="$(az keyvault secret show --vault-name "$VAULT" --name "$NAME" --query value -o tsv)"
            if [ "$VALUE" = "__SET_ME_BEFORE_THE_FIRST_DEPLOYMENT__" ]; then
              echo "::error::Key Vault secret $NAME in $VAULT still holds the placeholder. Set it: az keyvault secret set --vault-name $VAULT --name $NAME --value '...'"
              STATUS=1
            fi
          done
          exit $STATUS

      # Step 2: apply the database migrations with the NEW image before any traffic reaches it. Write
      # migrations so the previous version keeps working against the new schema (add first, remove later).
      - name: Run database migrations
        working-directory: deploy/azure
        run: |
          IMAGE="${REGISTRY_NAME}.azurecr.io/@@SLUG@@:${IMAGE_TAG}"
          terraform apply -input=false -auto-approve -var-file="environments/${TARGET}.tfvars" \
            -var "subscription_id=${ARM_SUBSCRIPTION_ID}" -var "registry_name=${REGISTRY_NAME}" \
            -var "registry_resource_group=${REGISTRY_RG}" -var "image=${IMAGE}" \
            -target=azurerm_container_app_job.migrate
          RG="$(terraform output -raw resource_group)"
          JOB="$(terraform output -raw migrate_job)"
          EXECUTION="$(az containerapp job start --name "$JOB" --resource-group "$RG" --query name -o tsv)"
          for _ in $(seq 1 60); do
            STATE="$(az containerapp job execution show --name "$JOB" --resource-group "$RG" \
              --job-execution-name "$EXECUTION" --query properties.status -o tsv)"
            case "$STATE" in
              Succeeded) exit 0 ;;
              Failed|Stopped|Degraded)
                echo "::error::The migration ended as $STATE. Logs: Container Apps job $JOB, Execution history. The running service was not changed."
                exit 1 ;;
            esac
            sleep 10
          done
          echo "::error::The migration did not finish in 10 minutes."
          exit 1

      # Step 3: single-revision mode keeps the previous revision serving until the new one is healthy.
      - name: Terraform apply (deploy the new image)
        working-directory: deploy/azure
        run: |
          terraform apply -input=false -auto-approve -var-file="environments/${TARGET}.tfvars" \
            -var "subscription_id=${ARM_SUBSCRIPTION_ID}" -var "registry_name=${REGISTRY_NAME}" \
            -var "registry_resource_group=${REGISTRY_RG}" \
            -var "image=${REGISTRY_NAME}.azurecr.io/@@SLUG@@:${IMAGE_TAG}"

      - name: Smoke test
        working-directory: deploy/azure
        run: |
          URL="$(terraform output -raw url)"
          curl --fail --silent --show-error --retry 10 --retry-delay 6 --retry-all-errors "${URL}/ready"
          echo "Deployed ${IMAGE_TAG} to ${TARGET}: ${URL}"
