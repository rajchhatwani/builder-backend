variable "project" {
  type    = string
  default = "deploy-gcp"
}

variable "project_id" {
  description = "Google Cloud project id that will host the environments."
  type        = string
}

variable "region" {
  type    = string
  default = "europe-west1"
}

variable "github_repo" {
  description = "owner/name of the repository whose workflows may deploy. Nobody else can use the identities."
  type        = string
  default     = "acme/notes"
}

variable "environments" {
  description = "One deploy identity per GitHub environment, so production can require approvals."
  type        = list(string)
  default     = ["dev", "staging", "prod"]
}
