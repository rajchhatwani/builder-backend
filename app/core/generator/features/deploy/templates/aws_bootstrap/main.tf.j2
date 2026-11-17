data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
}

# --- Terraform state: private, versioned, encrypted; locking uses a lock file in the bucket -------

resource "aws_s3_bucket" "state" {
  bucket = "${var.project}-tfstate-${local.account_id}"
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

data "aws_iam_policy_document" "state_tls_only" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = data.aws_iam_policy_document.state_tls_only.json
}

# --- Image registry: scanned on push, tags cannot be overwritten ----------------------------------

resource "aws_ecr_repository" "app" {
  name                 = var.project
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 50 newest images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 50 }
      action       = { type = "expire" }
    }]
  })
}

# --- GitHub OIDC: the workflow proves who it is with a short-lived token; no access key exists ----

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.create_oidc_provider ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

locals {
  oidc_provider_arn = var.create_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : "arn:aws:iam::${local.account_id}:oidc-provider/token.actions.githubusercontent.com"
}

data "aws_iam_policy_document" "trust" {
  for_each = toset(var.environments)

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    # Only jobs of THIS repository that run in THIS GitHub environment (where approvals live).
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:environment:${each.value}"]
    }
  }
}

# The ceiling of every role the pipeline creates for an environment (execution and task roles of the service):
# only what a running service needs. The deploy role may create or write roles only with this boundary attached.
locals {
  boundary_arns = { for e in var.environments : e => "arn:aws:iam::${local.account_id}:policy/deploy-boundary-${var.project}-${e}" }
}

data "aws_iam_policy_document" "boundary" {
  statement {
    sid = "WhatARunningServiceNeeds"
    actions = [
      "ecr:GetAuthorizationToken", "ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer",
      "logs:CreateLogStream", "logs:PutLogEvents",
      "secretsmanager:GetSecretValue",
      "sns:Publish",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "boundary" {
  for_each = toset(var.environments)
  name     = "deploy-boundary-${var.project}-${each.value}"
  policy   = data.aws_iam_policy_document.boundary.json
}

resource "aws_iam_role" "deploy" {
  for_each             = toset(var.environments)
  name                 = "deploy-${var.project}-${each.value}"  # outside the "<project>-*" pattern the policies manage
  assume_role_policy   = data.aws_iam_policy_document.trust[each.value].json
  max_session_duration = 3600
}

# What `terraform apply` of ../ needs. Network, load balancer and database actions cannot be limited to
# a name prefix, so this role is powerful inside its account: use a separate AWS account per
# environment for production, and review this policy before the first apply.
data "aws_iam_policy_document" "deploy" {
  for_each = toset(var.environments)

  statement {
    sid = "ManageTheStack"
    actions = [
      "ec2:*",
      "elasticloadbalancing:*",
      "rds:*",
      "wafv2:*",
      "application-autoscaling:*",
      "logs:*",
      "ecs:*",
      "secretsmanager:*",
      "cloudwatch:*",
      "ecr:GetAuthorizationToken",
      "tag:GetResources",
    ]
    resources = ["*"]
  }

  # Only the roles of THIS environment ("<project>-<env>-*"): the deploy roles ("deploy-<project>-<env>")
  # are outside the pattern, so no pipeline can rewrite another environment's role or its own.
  statement {
    sid = "RolesOfThisEnvironmentOnly"
    actions = [
      "iam:GetRole", "iam:UpdateRole", "iam:TagRole", "iam:UntagRole", "iam:DeleteRole",
      "iam:GetRolePolicy", "iam:DeleteRolePolicy", "iam:DetachRolePolicy",
      "iam:ListRolePolicies", "iam:ListAttachedRolePolicies", "iam:ListInstanceProfilesForRole",
      "iam:PassRole",
    ]
    resources = ["arn:aws:iam::${local.account_id}:role/${var.project}-${each.value}-*"]
  }

  statement {
    sid       = "ServiceLinkedRoles"
    actions   = ["iam:CreateServiceLinkedRole", "iam:GetRole"]
    resources = ["arn:aws:iam::${local.account_id}:role/aws-service-role/*"]
  }

  # Creating a role or writing an inline policy is only allowed when the role carries the permissions
  # boundary of this environment: whatever the pipeline writes into those roles can never exceed it.
  statement {
    sid       = "WriteRolesWithTheBoundaryOnly"
    actions   = ["iam:CreateRole", "iam:PutRolePolicy"]
    resources = ["arn:aws:iam::${local.account_id}:role/${var.project}-${each.value}-*"]
    condition {
      test     = "StringEquals"
      variable = "iam:PermissionsBoundary"
      values   = [local.boundary_arns[each.value]]
    }
  }

  # Attaching a managed policy is limited to the one ECS needs: no AdministratorAccess through this role.
  statement {
    sid       = "AttachTheEcsExecutionPolicyOnly"
    actions   = ["iam:AttachRolePolicy"]
    resources = ["arn:aws:iam::${local.account_id}:role/${var.project}-${each.value}-*"]
    condition {
      test     = "ArnEquals"
      variable = "iam:PolicyARN"
      values   = ["arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"]
    }
    condition {
      test     = "StringEquals"
      variable = "iam:PermissionsBoundary"
      values   = [local.boundary_arns[each.value]]
    }
  }

  statement {
    sid       = "NeverChangeTheBoundary"
    effect    = "Deny"
    actions   = ["iam:DeleteRolePermissionsBoundary", "iam:PutRolePermissionsBoundary", "iam:CreatePolicyVersion", "iam:DeletePolicy"]
    resources = ["*"]
  }

  statement {
    sid       = "PushImages"
    actions   = ["ecr:BatchCheckLayerAvailability", "ecr:CompleteLayerUpload", "ecr:InitiateLayerUpload", "ecr:PutImage", "ecr:UploadLayerPart", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:DescribeImages", "ecr:DescribeRepositories"]
    resources = [aws_ecr_repository.app.arn]
  }

  statement {
    sid       = "TerraformState"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"]
  }
}

resource "aws_iam_role_policy" "deploy" {
  for_each = toset(var.environments)
  name     = "deploy"
  role     = aws_iam_role.deploy[each.value].id
  policy   = data.aws_iam_policy_document.deploy[each.value].json
}
