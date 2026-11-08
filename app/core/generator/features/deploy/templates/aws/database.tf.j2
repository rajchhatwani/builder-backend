# PostgreSQL in private subnets. The password is generated here and stored in Secrets Manager as
# part of DATABASE_URL; it also lives in the Terraform state, so protect the state bucket (bootstrap/
# creates it encrypted, versioned and private) and limit who can read it.
resource "random_password" "db" {
  length  = 32
  special = false # letters and digits only: safe inside a connection URL
}

resource "aws_db_subnet_group" "main" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_instance" "main" {
  identifier     = local.name
  engine         = "postgres"
  engine_version = "16"
  instance_class = var.db_class

  allocated_storage     = var.db_storage_gb
  max_allocated_storage = var.db_storage_gb * 4
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = "app"
  username = "app"
  password = random_password.db.result

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false
  multi_az               = var.db_high_availability

  backup_retention_period         = var.deletion_protection ? 14 : 3
  deletion_protection             = var.deletion_protection
  skip_final_snapshot             = !var.deletion_protection
  final_snapshot_identifier       = var.deletion_protection ? "${local.name}-final" : null
  copy_tags_to_snapshot           = true
  auto_minor_version_upgrade      = true
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]
}
