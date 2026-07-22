#!/bin/bash
# Amazon Linux 2023 — Docker + app container (+ optional Caddy for TLS).
set -euxo pipefail

dnf update -y
dnf install -y docker openssl
systemctl enable --now docker
# Ensure SSM Session Manager works (AL2023 usually has the agent; force it on).
dnf install -y amazon-ssm-agent || true
systemctl enable --now amazon-ssm-agent || true
# EC2 Instance Connect (optional SSH without a persistent key).
dnf install -y ec2-instance-connect || true

REGION="${aws_region}"
ECR_HOST="${ecr_registry_host}"
IMAGE="${ecr_image}"

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ECR_HOST"

mkdir -p /opt/resume-agent/data /opt/resume-agent/caddy
chmod 711 /opt/resume-agent

if [[ ! -f /opt/resume-agent/.env ]]; then
  SECRET=$(openssl rand -hex 32)
  cat >/opt/resume-agent/.env <<EOF
SESSION_SECRET=$SECRET
DASHBOARD_BASE_URL=${dashboard_base_url}
OPENAI_API_KEY=
MODEL_NAME=gpt-4.1
DEFAULT_USER_ID=1
DAILY_RUN_USER_ID=1
GMAIL_ADDRESS=
GMAIL_APP_PASSWORD=
OUTPUTS_DIR=/data/outputs
PLAYWRIGHT_PROFILES_DIR=/data/playwright
DATABASE_URL=${database_url}
MYSQL_HOST=${db_host}
MYSQL_DATABASE=${db_name}
MYSQL_USER=${db_username}
MYSQL_PASSWORD=${db_password}
EOF
  chmod 600 /opt/resume-agent/.env
else
  # Keep existing secrets; refresh DB endpoint/password from Terraform.
  grep -vE '^(DATABASE_URL|MYSQL_HOST|MYSQL_DATABASE|MYSQL_USER|MYSQL_PASSWORD)=' /opt/resume-agent/.env > /opt/resume-agent/.env.tmp || true
  cat >>/opt/resume-agent/.env.tmp <<EOF
DATABASE_URL=${database_url}
MYSQL_HOST=${db_host}
MYSQL_DATABASE=${db_name}
MYSQL_USER=${db_username}
MYSQL_PASSWORD=${db_password}
EOF
  mv /opt/resume-agent/.env.tmp /opt/resume-agent/.env
  chmod 600 /opt/resume-agent/.env
fi

docker pull "$IMAGE"

docker rm -f resume-agent 2>/dev/null || true
# With Caddy (TLS hostname): bind loopback only. Otherwise expose :8000 publicly.
docker run -d --name resume-agent --restart unless-stopped \
  --log-driver json-file --log-opt max-size=10m --log-opt max-file=3 \
%{ if install_caddy ~}
  -p 127.0.0.1:8000:8000 \
%{ else ~}
  -p 8000:8000 \
%{ endif ~}
  -v /opt/resume-agent/data:/data \
  --env-file /opt/resume-agent/.env \
  "$IMAGE"

%{ if install_caddy ~}
cat >/opt/resume-agent/caddy/Caddyfile <<EOF
${caddyfile}
EOF

docker rm -f caddy 2>/dev/null || true
docker run -d --name caddy --restart unless-stopped \
  --log-driver json-file --log-opt max-size=5m --log-opt max-file=2 \
  -p 80:80 -p 443:443 \
  -v /opt/resume-agent/caddy/Caddyfile:/etc/caddy/Caddyfile:ro \
  -v caddy_data:/data \
  caddy:2-alpine
%{ endif ~}

echo "resume-agent user-data complete"
