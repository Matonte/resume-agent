# RDS MySQL for resume-agent (accounts, jobs, RAG chunks).
# Files (résumés, Playwright profiles, DOCX artifacts) stay on the EC2 volume.

resource "random_password" "db" {
  length  = 24
  special = false # alphanumeric only so .env / JDBC URLs stay simple
}

resource "aws_db_subnet_group" "app" {
  name       = "${var.project_name}-db"
  subnet_ids = data.aws_subnets.default.ids

  tags = merge(local.app_tags, {
    Name = "${var.project_name}-db"
  })
}

resource "aws_security_group" "db" {
  name_prefix = "${var.project_name}-db-"
  description = "MySQL only from app EC2 security group"
  vpc_id      = data.aws_vpc.this.id
  tags        = local.app_tags

  ingress {
    description     = "MySQL from app"
    from_port       = 3306
    to_port         = 3306
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_db_instance" "app" {
  identifier     = "${var.project_name}-mysql"
  engine         = "mysql"
  engine_version = var.db_engine_version
  instance_class = var.db_instance_class

  allocated_storage     = var.db_allocated_storage_gb
  max_allocated_storage = var.db_max_allocated_storage_gb
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = var.db_name
  username = var.db_username
  password = random_password.db.result

  db_subnet_group_name   = aws_db_subnet_group.app.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false
  multi_az               = var.db_multi_az

  backup_retention_period = var.db_backup_retention_days
  skip_final_snapshot     = var.db_skip_final_snapshot
  deletion_protection     = var.db_deletion_protection

  performance_insights_enabled = false
  auto_minor_version_upgrade   = true

  tags = merge(local.app_tags, {
    Name = "${var.project_name}-mysql"
  })
}

locals {
  database_url = format(
    "mysql+pymysql://%s:%s@%s:3306/%s",
    var.db_username,
    random_password.db.result,
    aws_db_instance.app.address,
    var.db_name,
  )
}
