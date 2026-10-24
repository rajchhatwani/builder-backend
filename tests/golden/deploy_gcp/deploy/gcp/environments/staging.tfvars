# staging: generated from the project spec (profile small).
# Edit the numbers to change capacity (cpu in millicores, memory in MB):
# no code change or rebuild is needed.
environment          = "staging"
region               = "europe-west1"
cpu                  = 1000
memory               = 1024
min_instances        = 1
max_instances        = 2
db_class             = "db-custom-1-3840"
db_storage_gb        = 20
db_high_availability = false
deletion_protection  = false
app_env              = "production"
