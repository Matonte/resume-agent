variable "aws_region" {
  type        = string
  description = "AWS region for all resources."
  default     = "us-east-1"
}

variable "project_name" {
  type        = string
  description = "Prefix for resource names."
  default     = "resume-agent"
}

variable "repository_name" {
  type        = string
  description = "ECR repository name for the resume-agent image."
  default     = "resume-agent"
}

variable "instance_type" {
  type        = string
  description = "Graviton (ARM) instance. t4g.large (8 GiB) recommended for resume-agent + contact-advisor + Playwright."
  default     = "t4g.large"
}

variable "root_volume_gb" {
  type        = number
  description = "Root gp3 volume size (artifacts + uploads + browser profiles grow over time)."
  default     = 40
}

variable "db_instance_class" {
  type        = string
  description = "RDS MySQL class (Graviton). db.t4g.micro is the cheap starting point."
  default     = "db.t4g.micro"
}

variable "db_engine_version" {
  type        = string
  description = "MySQL engine version."
  default     = "8.0"
}

variable "db_name" {
  type    = string
  default = "resume_agent"
}

variable "db_username" {
  type    = string
  default = "resume_agent"
}

variable "db_allocated_storage_gb" {
  type    = number
  default = 20
}

variable "db_max_allocated_storage_gb" {
  type        = number
  default     = 100
  description = "Autoscaling storage ceiling (gp3)."
}

variable "db_multi_az" {
  type        = bool
  default     = false
  description = "Multi-AZ roughly doubles RDS cost; leave false until you need HA."
}

variable "db_backup_retention_days" {
  type        = number
  default     = 0
  description = "0 or 1 for free-tier accounts (7+ is often rejected). Raise after upgrading the account plan."
}

variable "db_skip_final_snapshot" {
  type        = bool
  default     = true
  description = "Set false for production tear-down protection."
}

variable "db_deletion_protection" {
  type    = bool
  default = false
}

variable "public_subnet_id" {
  type        = string
  default     = null
  description = "Subnet for the instance (default: first subnet in the default VPC)."
}

variable "ssh_cidr_blocks" {
  type        = list(string)
  default     = []
  description = "CIDRs allowed to SSH (e.g. [\"203.0.113.10/32\"]). Empty = no port 22; use SSM Session Manager only."
}

variable "key_name" {
  type        = string
  default     = ""
  description = "Optional EC2 key pair name for SSH. Prefer SSM when empty."
}

variable "app_hostname" {
  type        = string
  default     = ""
  description = "FQDN for HTTPS (e.g. jobs.example.com). If set, user-data runs Caddy with Let's Encrypt. Create DNS A record to the Elastic IP (or set route53_zone_id)."
}

variable "route53_zone_id" {
  type        = string
  default     = ""
  description = "If set with app_hostname, creates an A record to the Elastic IP."
}
