# prod: generated from the project spec (profile medium).
# Edit the numbers to change capacity (cpu in millicores, memory in MB):
# no code change or rebuild is needed.
environment          = "prod"
region               = "westeurope"
cpu                  = 1000
memory               = 2048
min_instances        = 2
max_instances        = 8
db_class             = "GP_Standard_D2ds_v5"
db_storage_gb        = 50
db_high_availability = true
deletion_protection  = true
app_env              = "production"
