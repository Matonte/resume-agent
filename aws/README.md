# AWS: one EC2 (both agents) + RDS MySQL + Route53 + GitHub→ECR

**Billing:** You can ignore this folder until your AWS account can create billable resources. Until then, run everything locally; see [docs/CUTOVER_CHECKLIST.md](../docs/CUTOVER_CHECKLIST.md).

This layout is **intentionally minimal**: **one Graviton EC2 (`t4g.large`)** in the **default VPC**, **RDS MySQL**, **Elastic IP**, **ECR**, **optional Route53 A record**, **Caddy** on the box for **HTTPS** — **no NAT Gateway**, **no Application Load Balancer**.

Run **resume-agent** and (manually) **contact-advisor** containers on the **same EC2**. Structured data goes to **RDS**; uploads / Playwright / DOCX stay on the instance volume under `/data`.

**Commit `aws/terraform/.terraform.lock.hcl`** with the repo so `terraform apply` uses the same provider versions everywhere.

## Rough monthly cost (us-east-1 class, 2026-ish — verify in [AWS Pricing Calculator](https://calculator.aws/))

| Item | Typical |
|------|---------|
| **EC2 `t4g.large`** (8 GiB, on-demand) | **~\$45–55** |
| **EBS gp3** 40 GB | **~\$3–4** |
| **RDS `db.t4g.micro`** MySQL single-AZ + ~20 GB | **~\$14–20** |
| **Elastic IP** (attached to running instance) | **\$0** |
| **ECR** (small images, few tags) | **~\$0–1** |
| **Route53 hosted zone** (optional) | **\$0.50** + queries pennies |
| **Data transfer** (light personal / small team) | **often \$0–5** |
| **NAT Gateway / ALB** | **\$0** (not used) |

**Subtotal infrastructure:** about **\$65–85/mo** before **OpenAI** and your **domain** registrar.

**Why Graviton (`t4g`)** — lower \$ per GiB RAM than `t3` in most regions. CI builds **multi-arch** images (`linux/amd64` + `linux/arm64`) so the same tag runs on Graviton and on your laptop.

## What Terraform creates

- **ECR** repository + lifecycle policy (keep last 20 images).
- **AppRegistry application** (`resume-agent`) so the stack appears under **AWS Console → myApplications**.
- **IAM** role for the instance: **SSM Session Manager** + **ECR pull**.
- **Security group (app):** **80**, **443**, **8000** from the internet (tighten **8000** after HTTPS works); **22** only if you set `ssh_cidr_blocks`.
- **Security group (db):** MySQL **3306** only from the app SG.
- **RDS MySQL** (`db.t4g.micro` by default) + subnet group.
- **EC2** Amazon Linux 2023 **ARM64** + **user-data** that installs Docker, logs in to ECR, writes `DATABASE_URL` into `/opt/resume-agent/.env`, runs the app container, and optionally **Caddy** for TLS.
- **Elastic IP** + association.
- **Optional** Route53 **A** record if `route53_zone_id` and `app_hostname` are set.

State, secrets, and `terraform.tfvars` are your responsibility — do **not** commit real tfvars.

## Deploy steps

1. **Tools:** [Terraform](https://developer.hashicorp.com/terraform/install) ≥ 1.5, [AWS CLI](https://docs.aws.amazon.com/cli/) configured (`aws sts get-caller-identity` works).

2. **Build & push the image to ECR** (after first `terraform apply` creates the repo):
   - **GitHub:** set secrets `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `AWS_ECR_REPOSITORY` (full URI from `terraform output ecr_repository_url`), then run workflow **Deploy to ECR**.
   - Or locally: `aws ecr get-login-password ... | docker login ...` then `docker buildx build --platform linux/arm64 --push -t $URI:latest .`

3. **Configure Terraform**
   ```bash
   cd aws/terraform
   cp terraform.tfvars.example terraform.tfvars
   # edit: region, instance_type (default t4g.large), optional app_hostname + route53_zone_id
   terraform init
   ```

   **First time only — avoid a failed cloud-init when ECR is empty:** create the repo, push an image, then create the VM + RDS:

   ```bash
   terraform apply -target=aws_ecr_repository.resume_agent -target=aws_ecr_lifecycle_policy.resume_agent
   # Push :latest to the repository URL from `terraform output ecr_repository_url`
   terraform apply
   ```

   If you already ran a full `apply` before any image existed, SSM in and run `docker pull` + `docker run` by hand, or `terraform apply -replace=aws_instance.app` after the image exists to re-run user-data.

4. **DNS**
   - If **not** using Route53 in Terraform: create an **A record** for your hostname to the **Elastic IP** from output.
   - Wait for propagation before relying on Let’s Encrypt.

5. **Secrets on the instance** (no SSH required):
   ```bash
   aws ssm start-session --target "$(terraform output -raw instance_id)" --region us-east-1
   sudo nano /opt/resume-agent/.env
   # Set OPENAI_API_KEY, SESSION_SECRET (optional rotate), GMAIL_*, DASHBOARD_BASE_URL=https://your-hostname
   # DATABASE_URL / MYSQL_* are written by user-data from Terraform — usually leave them.
   # Optional Contact Advisor on the same host:
   #   MEETING_ADVISOR_URL=http://127.0.0.1:5003
   #   CONTACT_ADVISOR_SERVICE_URL=http://127.0.0.1:5000
   sudo docker restart resume-agent
   ```

6. **Smoke test**
   - `https://<hostname>/api/health` (or `http://<EIP>:8000/api/health` if hostname not set yet).

7. **Daily run** (cron on the **host**):
   ```cron
   5 14 * * * docker exec resume-agent python -m app.jobs.daily_run >> /var/log/resume-agent-cron.log 2>&1
   ```

8. **Playwright logins** — `docker exec -it resume-agent python scripts/login_once.py <site>` so profiles persist under `/data/playwright`.

9. **Contact Advisor (same EC2)** — not automated in user-data yet. Run its containers on the host, bind to `127.0.0.1`, set the env vars above. Do **not** open 5000/5003 publicly.

## Data layout

| Data | Where |
|------|--------|
| Users, jobs, RAG embeddings, onboarding metadata | **RDS MySQL** (`DATABASE_URL`) |
| Résumé files, tailored DOCX, Playwright profiles | **EC2 `/data`** |
| Local/dev without RDS | SQLite under `outputs/jobs.sqlite` (leave `DATABASE_URL` unset) |

## Security notes

- Prefer **SSM Session Manager** over SSH (`ssh_cidr_blocks = []`).
- After Caddy works, lock down port **8000**.
- Rotate **`SESSION_SECRET`** if leaked.
- RDS is **not** publicly accessible; only the app SG can reach 3306.

## When to upgrade

- **RAM pressure:** larger `t4g` or off-peak scrapes.
- **RDS HA:** `db_multi_az = true` (~2× RDS instance cost).
- **Multi-instance app:** needs shared file storage (EFS/S3) — different architecture.
