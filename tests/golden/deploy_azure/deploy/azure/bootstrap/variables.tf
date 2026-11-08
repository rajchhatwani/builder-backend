variable "project" {
  type    = string
  default = "deploy-azure"
}

variable "subscription_id" {
  description = "Azure subscription that will host the environments."
  type        = string
}

variable "region" {
  type    = string
  default = "westeurope"
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
