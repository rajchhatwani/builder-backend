terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Remote state with native locking (S3 lockfile, Terraform 1.10 or newer). The bucket is created by
  # bootstrap/; its name and the state key are passed at init time (see ../../docs/DEPLOYMENT.md):
  #   terraform init -backend-config="bucket=..." -backend-config="key=deploy-aws/<env>/terraform.tfstate" \
  #     -backend-config="region=..." -backend-config="use_lockfile=true" -backend-config="encrypt=true"
  backend "s3" {}
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
