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

output "rds_endpoint" {
  description = "MySQL hostname (private). App reaches it via DATABASE_URL on the instance."
  value       = aws_db_instance.app.address
}

output "rds_db_name" {
  value = aws_db_instance.app.db_name
}

output "env_file_on_instance" {
  value = "/opt/resume-agent/.env — add OPENAI_API_KEY, Gmail, Contact Advisor URLs, then: docker restart resume-agent"
}

output "aws_console_application" {
  description = "myApplications entry in the AWS Console (us-east-1)."
  value       = "https://${var.aws_region}.console.aws.amazon.com/systems-manager/appmanager/application/${aws_servicecatalogappregistry_application.resume_agent.id}?region=${var.aws_region}"
}

output "application_id" {
  description = "AppRegistry / myApplications application id"
  value       = aws_servicecatalogappregistry_application.resume_agent.id
}

output "github_actions_role_arn" {
  description = "OIDC role for GitHub Actions (secret AWS_ROLE_TO_ASSUME)."
  value       = aws_iam_role.github_actions.arn
}
