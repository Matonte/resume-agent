#!/bin/bash
# Amazon Linux 2023 — Docker + app container (+ optional Caddy for TLS).
set -euxo pipefail

dnf update -y
dnf install -y docker openssl
systemctl enable --now docker

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
EOF
  chmod 600 /opt/resume-agent/.env
fi

docker pull "$IMAGE"

docker rm -f resume-agent 2>/dev/null || true
docker run -d --name resume-agent --restart unless-stopped \
  --log-driver json-file --log-opt max-size=10m --log-opt max-file=3 \
  -p 127.0.0.1:8000:8000 \
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
