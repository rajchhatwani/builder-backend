locals {
  # Secrets the application reads from its environment. Terraform creates the empty containers; YOU
  # set their values (never in this repository or in a .tfvars file):
  #   aws secretsmanager put-secret-value --secret-id deploy-aws/<environment>/<NAME> --secret-string '...'
  app_secret_names = ["AUTH_JWT_SECRET"]
}

resource "aws_secretsmanager_secret" "database_url" {
  name                    = "${var.project}/${var.environment}/DATABASE_URL"
  recovery_window_in_days = var.deletion_protection ? 30 : 0
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id = aws_secretsmanager_secret.database_url.id
  # ssl=require: RDS for PostgreSQL 15 and newer refuses unencrypted connections.
  secret_string = "postgresql+asyncpg://app:${random_password.db.result}@${aws_db_instance.main.address}:5432/app?ssl=require"
}

resource "aws_secretsmanager_secret" "app" {
  for_each                = toset(local.app_secret_names)
  name                    = "${var.project}/${var.environment}/${each.value}"
  recovery_window_in_days = var.deletion_protection ? 30 : 0
}
