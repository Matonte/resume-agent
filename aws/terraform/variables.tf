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
  description = "Graviton (ARM) instance. t4g.medium = 4 GiB RAM (minimum practical for Playwright + users)."
  default     = "t4g.medium"
}

variable "root_volume_gb" {
  type        = number
  description = "Root gp3 volume size (artifacts + SQLite + browser profiles grow over time)."
  default     = 40
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
