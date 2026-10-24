# staging: generated from the project spec (profile small).
# Edit the numbers to change capacity (cpu in millicores, memory in MB):
# no code change or rebuild is needed.
environment          = "staging"
region               = "eu-west-1"
cpu                  = 512
memory               = 1024
min_instances        = 1
max_instances        = 2
db_class             = "db.t4g.small"
db_storage_gb        = 20
db_high_availability = false
deletion_protection  = false
app_env              = "production"

# HTTPS needs a certificate from AWS Certificate Manager in this region:
# acm_certificate_arn = "arn:aws:acm:<region>:<account>:certificate/<id>"
allow_http         = false
enable_waf         = true
single_nat_gateway = true
