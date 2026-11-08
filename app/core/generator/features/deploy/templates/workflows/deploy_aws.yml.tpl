# Deployment of @@PROJECT@@ to AWS (generated).
#
#   push to main            -> build once, deploy to @@FIRST_ENV@@
#   Actions > Deploy > Run  -> choose an environment (and an image tag that is already built) to promote
#
# Signs in to AWS with GitHub's short-lived OIDC token: there is no access key anywhere. Each GitHub
# environment (@@ENV_LIST@@) has its own role (variable AWS_ROLE_ARN), so production can require
# reviewers in Settings > Environments. One-time setup: docs/DEPLOYMENT.md.
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
      id-token: write # the OIDC token, for AWS and for signing the image
    env:
      TARGET: ${{ inputs.environment || '@@FIRST_ENV@@' }}
      AWS_REGION: ${{ vars.AWS_REGION || '@@REGION@@' }}
      TF_STATE_BUCKET: ${{ vars.TF_STATE_BUCKET }}
      REGISTRY_REPO: ${{ vars.ECR_REPOSITORY_URL }}
      IMAGE_TAG: ${{ inputs.image_tag || github.sha }}
    steps:
      - uses: @@pin:actions/checkout@@
        with:
          persist-credentials: false

      - name: Sign in to AWS (OIDC)
        uses: @@pin:aws-actions/configure-aws-credentials@@
        with:
          role-to-assume: ${{ vars.AWS_ROLE_ARN }}
          aws-region: ${{ env.AWS_REGION }}

      - name: Sign in to the registry
        uses: @@pin:aws-actions/amazon-ecr-login@@

      - uses: @@pin:docker/setup-buildx-action@@

      - name: Build and push the image (skipped when promoting an existing tag)
        id: build
        if: ${{ inputs.image_tag == '' }}
        uses: @@pin:docker/build-push-action@@
        with:
          context: .
          push: true
          tags: ${{ env.REGISTRY_REPO }}:${{ env.IMAGE_TAG }}
          provenance: mode=max
          sbom: true
          cache-from: type=gha
          cache-to: type=gha,mode=max

      - name: Make sure the image exists
        run: |
          aws ecr describe-images --repository-name "${REGISTRY_REPO##*/}" \
            --image-ids imageTag="$IMAGE_TAG" --query 'imageDetails[0].imageDigest' --output text

      - name: Sign the image (keyless, recorded in the public transparency log)
        if: ${{ inputs.image_tag == '' }}
        uses: @@pin:sigstore/cosign-installer@@
      - if: ${{ inputs.image_tag == '' }}
        run: cosign sign --yes "${REGISTRY_REPO}@${{ steps.build.outputs.digest }}"

      - uses: @@pin:hashicorp/setup-terraform@@
        with:
          terraform_version: @@TERRAFORM_VERSION@@
          terraform_wrapper: false

      - name: Terraform init
        working-directory: deploy/aws
        run: |
          terraform init -input=false \
            -backend-config="bucket=${TF_STATE_BUCKET}" \
            -backend-config="key=@@SLUG@@/${TARGET}/terraform.tfstate" \
            -backend-config="region=${AWS_REGION}" \
            -backend-config="use_lockfile=true" \
            -backend-config="encrypt=true"

      # Step 1: make sure the infrastructure exists and is current while the service keeps running the
      # image it already has (the first deployment has none, so it starts from the new one).
      - name: Terraform apply (infrastructure, service unchanged)
        working-directory: deploy/aws
        run: |
          CURRENT="$(terraform output -raw deployed_image 2>/dev/null || true)"
          terraform apply -input=false -auto-approve -var-file="environments/${TARGET}.tfvars" \
            -var "image=${CURRENT:-${REGISTRY_REPO}:${IMAGE_TAG}}"

      # Step 2: apply the database migrations with the NEW image before any traffic reaches it. Write
      # migrations so the previous version keeps working against the new schema (add first, remove later).
      - name: Run database migrations
        working-directory: deploy/aws
        run: |
          IMAGE="${REGISTRY_REPO}:${IMAGE_TAG}"
          terraform apply -input=false -auto-approve -var-file="environments/${TARGET}.tfvars" \
            -var "image=${IMAGE}" -target=aws_ecs_task_definition.migrate
          CLUSTER="$(terraform output -raw cluster_name)"
          TASK_DEF="$(terraform output -raw migrate_task_definition)"
          SUBNETS="$(terraform output -json private_subnet_ids | jq -r 'join(",")')"
          SG="$(terraform output -raw tasks_security_group_id)"
          TASK_ARN="$(aws ecs run-task --cluster "$CLUSTER" --task-definition "$TASK_DEF" --launch-type FARGATE \
            --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SG],assignPublicIp=DISABLED}" \
            --query 'tasks[0].taskArn' --output text)"
          aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$TASK_ARN"
          EXIT_CODE="$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$TASK_ARN" \
            --query 'tasks[0].containers[0].exitCode' --output text)"
          if [ "$EXIT_CODE" != "0" ]; then
            echo "::error::The migration failed (exit code $EXIT_CODE). Logs: CloudWatch group /ecs/@@SLUG@@-${TARGET}, stream prefix migrate. The running service was not changed."
            exit 1
          fi

      # Step 3: roll the service to the new image. If its tasks never become healthy, ECS stops the
      # deployment and rolls back to the previous task definition by itself (deployment circuit breaker).
      - name: Terraform apply (deploy the new image)
        working-directory: deploy/aws
        run: |
          terraform apply -input=false -auto-approve -var-file="environments/${TARGET}.tfvars" \
            -var "image=${REGISTRY_REPO}:${IMAGE_TAG}"

      - name: Wait until the service is stable
        working-directory: deploy/aws
        run: |
          aws ecs wait services-stable --cluster "$(terraform output -raw cluster_name)" \
            --services "$(terraform output -raw service_name)"

      - name: Smoke test
        working-directory: deploy/aws
        run: |
          URL="$(terraform output -raw url)"
          curl --fail --silent --show-error --retry 10 --retry-delay 6 --retry-all-errors "${URL}/ready"
          echo "Deployed ${IMAGE_TAG} to ${TARGET}: ${URL}"
