output "url" {
  description = "Where the service answers. Point your DNS name at the load balancer for a friendly address."
  value       = "${local.https ? "https" : "http"}://${aws_lb.main.dns_name}"
}

output "load_balancer_dns_name" {
  value = aws_lb.main.dns_name
}

output "cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "service_name" {
  value = aws_ecs_service.app.name
}

output "migrate_task_definition" {
  description = "Run once per deployment with the pipeline (see .github/workflows/deploy.yml)."
  value       = aws_ecs_task_definition.migrate.arn
}

output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}

output "tasks_security_group_id" {
  value = aws_security_group.tasks.id
}

output "secrets_to_fill" {
  description = "Secrets Manager secrets whose values you must set before the first deployment."
  value       = [for s in aws_secretsmanager_secret.app : s.name]
}

output "deployed_image" {
  description = "The image the service runs now. The pipeline starts from it, so a first step can update the infrastructure without touching the service."
  value       = jsondecode(aws_ecs_task_definition.app.container_definitions)[0].image
}
