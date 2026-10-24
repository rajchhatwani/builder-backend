output "state_bucket" {
  value = aws_s3_bucket.state.bucket
}

output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}

output "deploy_role_arns" {
  description = "Set each as the AWS_ROLE_ARN variable of the matching GitHub environment."
  value       = { for env, role in aws_iam_role.deploy : env => role.arn }
}

output "region" {
  value = var.region
}
