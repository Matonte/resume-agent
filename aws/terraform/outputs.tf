output "ecr_repository_url" {
  description = "docker push $ecr_repository_url:latest (after aws ecr get-login-password)"
  value       = aws_ecr_repository.resume_agent.repository_url
}

output "ecr_registry_id" {
  value = aws_ecr_repository.resume_agent.registry_id
}

output "elastic_ip" {
  description = "Public IP — point your DNS A record here if not using Route53."
  value       = aws_eip.app.public_ip
}

output "public_url_http" {
  description = "Direct to FastAPI (no TLS) while testing."
  value       = "http://${aws_eip.app.public_ip}:8000"
}

output "public_url_https" {
  description = "Set app_hostname to enable."
  value       = var.app_hostname != "" ? "https://${var.app_hostname}" : "(set var.app_hostname)"
}

output "instance_id" {
  value = aws_instance.app.id
}

output "ssm_session_hint" {
  description = "Shell without SSH: aws ssm start-session --target <instance_id>"
  value       = "aws ssm start-session --target ${aws_instance.app.id} --region ${var.aws_region}"
}

output "env_file_on_instance" {
  value = "/opt/resume-agent/.env — add OPENAI_API_KEY, Gmail, etc. then: docker restart resume-agent"
}
