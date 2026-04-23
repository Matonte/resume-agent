# Cheapest “full AWS” pattern for this app: one Graviton (t4g) instance in the
# default VPC — no NAT Gateway, no Application Load Balancer.
# Requires linux/arm64 (and linux/amd64) images from CI (see .github/workflows).

data "aws_vpc" "this" {
  default = true
}

data "aws_ami" "al2023_arm" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-kernel-*-arm64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "app" {
  name               = "${var.project_name}-ec2"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "ecr_read" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

resource "aws_iam_instance_profile" "app" {
  name = "${var.project_name}-ec2"
  role = aws_iam_role.app.name
}

resource "aws_security_group" "app" {
  name_prefix = "${var.project_name}-"
  description = "Resume agent web + optional SSH"
  vpc_id      = data.aws_vpc.this.id

  ingress {
    description = "HTTP (ACME / redirect)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS (Caddy)"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Direct FastAPI (lock down after TLS working)"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  dynamic "ingress" {
    for_each = var.ssh_cidr_blocks
    content {
      description = "SSH (optional)"
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
    }
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

resource "aws_eip" "app" {
  domain = "vpc"
  tags = {
    Name = "${var.project_name}-eip"
  }
}

locals {
  ecr_host                 = split("/", aws_ecr_repository.resume_agent.repository_url)[0]
  dashboard_base_url       = var.app_hostname != "" ? "https://${var.app_hostname}" : "http://${aws_eip.app.public_ip}:8000"
  install_caddy            = var.app_hostname != ""
  caddyfile                = local.install_caddy ? "${var.app_hostname} {\n  reverse_proxy 127.0.0.1:8000\n}\n" : ""
  user_data                = base64encode(templatefile("${path.module}/user-data.sh.tpl", {
    ecr_image            = "${aws_ecr_repository.resume_agent.repository_url}:latest"
    ecr_registry_host    = local.ecr_host
    aws_region           = var.aws_region
    dashboard_base_url   = local.dashboard_base_url
    install_caddy        = local.install_caddy
    caddyfile            = local.caddyfile
  }))
}

resource "aws_instance" "app" {
  ami                    = data.aws_ami.al2023_arm.id
  instance_type          = var.instance_type
  subnet_id              = var.public_subnet_id != null ? var.public_subnet_id : tolist(data.aws_subnets.default.ids)[0]
  vpc_security_group_ids = [aws_security_group.app.id]
  iam_instance_profile   = aws_iam_instance_profile.app.name

  user_data                   = local.user_data
  user_data_replace_on_change = true

  root_block_device {
    volume_type = "gp3"
    volume_size = var.root_volume_gb
    encrypted   = true
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  tags = {
    Name = "${var.project_name}-app"
  }
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.this.id]
  }
}

resource "aws_eip_association" "app" {
  instance_id   = aws_instance.app.id
  allocation_id = aws_eip.app.id
}

resource "aws_route53_record" "app" {
  count   = var.route53_zone_id != "" && var.app_hostname != "" ? 1 : 0
  zone_id = var.route53_zone_id
  name    = var.app_hostname
  type    = "A"
  ttl     = 300
  records = [aws_eip.app.public_ip]
}
