"""Pinned third-party versions used by generated pipelines and Terraform.

GitHub Actions are pinned to a full commit SHA (a moving tag such as v4 can be re-pointed by whoever
controls the action's repository; a SHA cannot). The tag is kept as a comment so a person can read
it and so a bot (Dependabot, Renovate) can propose updates. Looked up on 2026-10-24.
"""

TERRAFORM_VERSION = "1.17.0"

# action -> (tag, commit sha of that tag)
ACTION_PINS: dict[str, tuple[str, str]] = {
    "actions/checkout": ("v7.0.1", "3d3c42e5aac5ba805825da76410c181273ba90b1"),
    "actions/setup-python": ("v7.1.0", "6d4fd22b20465ccc0f7354476588e8df7c9ca0e0"),
    "docker/setup-buildx-action": ("v4.4.1", "f87e5991a6d7451dcb8d9637bfbc97413f497069"),
    "docker/login-action": ("v4.7.0", "81c6f93d4bc991e510b342a00b419b3bb4efc5c6"),
    "docker/build-push-action": ("v7.4.0", "c3c9e263c25d99ce0380d002d59b67737d91b0dc"),
    "aquasecurity/trivy-action": ("v0.36.0", "ed142fd0673e97e23eac54620cfb913e5ce36c25"),
    "anchore/sbom-action": ("v0.24.3", "66cbf4bc1f1c0d2edc94016e65bc221b6bb0ad6c"),
    "sigstore/cosign-installer": ("v4.1.2", "6f9f17788090df1f26f669e9d70d6ae9567deba6"),
    "aws-actions/configure-aws-credentials": (
        "v6.3.0",
        "e1253824e5c10ff9df46874f81ed3ec929e19cfd",
    ),
    "aws-actions/amazon-ecr-login": ("v2.1.7", "03f1aad4c6c7ffd436567f42f9384779290529bd"),
    "azure/login": ("v3.1.0", "a641126d1b8aa4d1fa005f4f92df94a3a4c4c906"),
    "google-github-actions/auth": ("v3", "7c6bc770dae815cd3e89ee6cdf493a5fab2cc093"),
    "google-github-actions/setup-gcloud": ("v3.0.1", "aa5489c8933f4cc7a4f7d45035b3b1440c9c10db"),
    "hashicorp/setup-terraform": ("v4.0.1", "dfe3c3f87815947d99a8997f908cb6525fc44e9e"),
    "actions/upload-artifact": ("v7.0.2", "cf430e030ddbb5b0abf93d22962f4752f3646cd9"),
}

IMAGES = {
    "postgres": "postgres:16-alpine",
}


def pin(action: str) -> str:
    """`owner/name@<sha> # <tag>` for use in a workflow's `uses:`."""
    tag, sha = ACTION_PINS[action]
    return f"{action}@{sha} # {tag}"
