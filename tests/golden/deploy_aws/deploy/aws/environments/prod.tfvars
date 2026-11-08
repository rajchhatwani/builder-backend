# prod: generated from the project spec (profile medium).
# Edit the numbers to change capacity (cpu in millicores, memory in MB):
# no code change or rebuild is needed.
environment          = "prod"
region               = "eu-west-1"
cpu                  = 1024
memory               = 2048
min_instances        = 2
max_instances        = 8
db_class             = "db.m7g.large"
db_storage_gb        = 50
db_high_availability = true
deletion_protection  = true
app_env              = "production"

# HTTPS needs a certificate from AWS Certificate Manager in this region:
# acm_certificate_arn = "arn:aws:acm:<region>:<account>:certificate/<id>"
allow_http         = false
enable_waf         = true
single_nat_gateway = false
