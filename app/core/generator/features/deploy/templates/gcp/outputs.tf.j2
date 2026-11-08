output "url" {
  description = "Where the service answers (HTTPS, with a certificate managed by Google)."
  value       = google_cloud_run_v2_service.app.uri
}

output "service_name" {
  value = google_cloud_run_v2_service.app.name
}

output "migrate_job" {
  description = "Run once per deployment with the pipeline (see .github/workflows/deploy.yml)."
  value       = google_cloud_run_v2_job.migrate.name
}

output "secrets_to_fill" {
  description = "Secret Manager secrets whose values you must set before the first deployment."
  value       = [for s in google_secret_manager_secret.app : s.secret_id]
}

output "deployed_image" {
  description = "The image the service runs now. The pipeline starts from it, so a first step can update the infrastructure without touching the service."
  value       = google_cloud_run_v2_service.app.template[0].containers[0].image
}
