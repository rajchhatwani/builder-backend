variable "project" {
  type    = string
  default = "deploy-aws"
}

variable "region" {
  type    = string
  default = "eu-west-1"
}

variable "github_repo" {
  description = "owner/name of the repository whose workflows may deploy. Nobody else can assume the roles."
  type        = string
  default     = "acme/notes"
}

variable "environments" {
  description = "One deploy role per GitHub environment, so production can require approvals."
  type        = list(string)
  default     = ["dev", "staging", "prod"]
}

variable "create_oidc_provider" {
  description = "Set false when this AWS account already has the GitHub OIDC provider."
  type        = bool
  default     = true
}
