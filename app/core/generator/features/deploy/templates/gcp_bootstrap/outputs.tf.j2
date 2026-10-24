output "state_bucket" {
  value = google_storage_bucket.state.name
}

output "registry" {
  description = "Image repository: <this>/<image name>:<tag>."
  value       = "${google_artifact_registry_repository.app.location}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.app.repository_id}"
}

output "workload_identity_provider" {
  description = "Set as the GCP_WORKLOAD_IDENTITY_PROVIDER variable of every GitHub environment."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "deploy_service_accounts" {
  description = "Set each as the GCP_SERVICE_ACCOUNT variable of the matching GitHub environment."
  value       = { for env, sa in google_service_account.deploy : env => sa.email }
}
