# Run ONCE per Google Cloud project by an administrator, with your own credentials
# (gcloud auth application-default login). It creates what the pipeline needs before it can run: the
# Terraform state bucket, the image registry, and the Workload Identity Federation that lets this
# repository's GitHub Actions workflows act as a service account without any stored key. Its own state
# stays local (terraform.tfstate here): keep that file safe.
terraform {
  required_version = ">= 1.10"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
