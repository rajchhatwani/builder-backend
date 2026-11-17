data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# Used by ECS itself: pull the image, write logs, read exactly the secrets this service names.
data "aws_caller_identity" "current" {}

locals {
  # Created by the bootstrap; the pipeline may only create roles that carry it.
  permissions_boundary = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/deploy-boundary-${local.name}"
}

resource "aws_iam_role" "execution" {
  name                 = "${local.name}-execution"
  permissions_boundary = local.permissions_boundary
  assume_role_policy   = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "read_secrets" {
  statement {
    actions = ["secretsmanager:GetSecretValue"]
    resources = concat(
      [aws_secretsmanager_secret.database_url.arn],
      [for s in aws_secretsmanager_secret.app : s.arn],
    )
  }
}

resource "aws_iam_role_policy" "read_secrets" {
  name   = "read-secrets"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.read_secrets.json
}

# The identity of the running application. It has no permissions beyond what the project needs: the service
# talks to its database and to the outside world. Add policies here when it needs another AWS service.
resource "aws_iam_role" "task" {
  name                 = "${local.name}-task"
  permissions_boundary = local.permissions_boundary
  assume_role_policy   = data.aws_iam_policy_document.ecs_assume.json
}

# Text-message codes (auth.sms_provider = aws_sns) are sent with sns:Publish to phone numbers.
resource "aws_iam_role_policy" "task_sns" {
  name = "sms"
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["sns:Publish"], Resource = "*" }]
  })
}
