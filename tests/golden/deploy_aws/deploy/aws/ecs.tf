locals {
  # The container runs the server only. Database migrations are a separate one-off task (below), run
  # by the pipeline before traffic moves, so several instances never migrate at the same time.
  serve_command = ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers $${UVICORN_WORKERS:-1}"]

  base_env = {
    APP_ENV         = var.app_env
    LOG_LEVEL       = "INFO"
    UVICORN_WORKERS = "1"
    DB_POOL_SIZE    = "5"
    DB_MAX_OVERFLOW = "5"
  }
  env_vars = merge(local.base_env, var.app_env_vars)

  secret_refs = concat(
    [{ name = "DATABASE_URL", valueFrom = aws_secretsmanager_secret.database_url.arn }],
    [for name, s in aws_secretsmanager_secret.app : { name = name, valueFrom = s.arn }],
  )
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${local.name}"
  retention_in_days = var.log_retention_days
}

resource "aws_ecs_cluster" "main" {
  name = local.name

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_ecs_task_definition" "app" {
  family                   = local.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.cpu)
  memory                   = tostring(var.memory)
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name         = "app"
      image        = var.image
      essential    = true
      command      = local.serve_command
      stopTimeout  = 30
      portMappings = [{ containerPort = 8000, protocol = "tcp" }]
      environment  = [for k, v in local.env_vars : { name = k, value = v }]
      secrets      = local.secret_refs
      healthCheck = {
        command     = ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
        interval    = 15
        timeout     = 5
        retries     = 3
        startPeriod = 30
      }
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.app.name
          awslogs-region        = var.region
          awslogs-stream-prefix = "app"
        }
      }
    }
  ])
}

# Same image and settings, different command: applies the database migrations once.
resource "aws_ecs_task_definition" "migrate" {
  family                   = "${local.name}-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name        = "migrate"
      image       = var.image
      essential   = true
      command     = ["alembic", "upgrade", "head"]
      environment = [for k, v in local.env_vars : { name = k, value = v }]
      secrets     = local.secret_refs
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.app.name
          awslogs-region        = var.region
          awslogs-stream-prefix = "migrate"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "app" {
  name            = "app"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = var.min_instances
  launch_type     = "FARGATE"

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 60
  propagate_tags                     = "SERVICE"

  # A deployment whose tasks never become healthy is stopped and rolled back to the last good one.
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.app.arn
    container_name   = "app"
    container_port   = 8000
  }

  lifecycle {
    ignore_changes = [desired_count] # owned by autoscaling
  }

  depends_on = [aws_lb_listener.http]
}

resource "aws_appautoscaling_target" "app" {
  service_namespace  = "ecs"
  scalable_dimension = "ecs:service:DesiredCount"
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.app.name}"
  min_capacity       = var.min_instances
  max_capacity       = var.max_instances
}

resource "aws_appautoscaling_policy" "cpu" {
  name               = "${local.name}-cpu"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.app.service_namespace
  scalable_dimension = aws_appautoscaling_target.app.scalable_dimension
  resource_id        = aws_appautoscaling_target.app.resource_id

  target_tracking_scaling_policy_configuration {
    target_value       = 60
    scale_in_cooldown  = 300
    scale_out_cooldown = 60

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}
