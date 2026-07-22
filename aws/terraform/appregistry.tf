# Shows up under AWS Console → myApplications (AppRegistry).

resource "aws_servicecatalogappregistry_application" "resume_agent" {
  name        = var.project_name
  description = "Resume Agent — FastAPI job tailor on EC2 with RDS MySQL and ECR"
}

locals {
  # Merge this into every resource that should appear under the application.
  app_tags = merge(
    aws_servicecatalogappregistry_application.resume_agent.application_tag,
    {
      Project = var.project_name
    }
  )
}
