# AWS: cheapest “full stack” for multiple users

**Billing:** You can ignore this folder until your AWS account can create billable resources. Until then, run everything locally; see [docs/CUTOVER_CHECKLIST.md](../docs/CUTOVER_CHECKLIST.md).

This layout is **intentionally minimal**: **one Graviton EC2** in the **default VPC**, **Elastic IP**, **ECR**, **optional Route53 A record**, **Caddy** on the box for **HTTPS** — **no NAT Gateway**, **no Application Load Balancer** (those two alone are often **~\$35–45/mo** before compute).

**Commit `aws/terraform/.terraform.lock.hcl`** with the repo so `terraform apply` uses the same provider versions everywhere.

The app already supports **multiple signed-in users** and **SQLite** on disk; a **single instance** is the right shape until you outgrow one machine.

## Rough monthly cost (us-east-1 class, 2026-ish — verify in [AWS Pricing Calculator](https://calculator.aws/))

| Item | Typical |
|------|---------|
| **EC2 `t4g.medium`** (4 GiB, on-demand) | **~\$24–28** |
| **EBS gp3** 40 GB | **~\$3–4** |
| **Elastic IP** (attached to running instance) | **\$0** |
| **ECR** (small images, few tags) | **~\$0–1** |
| **Route53 hosted zone** (optional) | **\$0.50** + queries pennies |
| **Data transfer** (light personal / small team) | **often \$0–5** |
| **NAT Gateway** | **\$0** (not used) |
| **ALB** | **\$0** (not used) |

**Subtotal infrastructure:** about **\$28–40/mo** before **OpenAI** and your **domain** registrar.

**Why Graviton (`t4g`)** — lower \$ per GiB RAM than `t3` in most regions. CI builds **multi-arch** images (`linux/amd64` + `linux/arm64`) so the same tag runs on Graviton and on your laptop.

## What Terraform creates

- **ECR** repository + lifecycle policy (keep last 20 images).
- **IAM** role for the instance: **SSM Session Manager** + **ECR pull**.
- **Security group:** **80**, **443**, **8000** from the internet (tighten **8000** after HTTPS works); **22** only if you set `ssh_cidr_blocks`.
- **EC2** Amazon Linux 2023 **ARM64** + **user-data** that installs Docker, logs in to ECR, runs the app container, and optionally **Caddy** for TLS.
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
   # edit: region, optional app_hostname + route53_zone_id, optional ssh_cidr_blocks
   terraform init
   ```

   **First time only — avoid a failed cloud-init when ECR is empty:** create the repo, push an image, then create the VM:

   ```bash
   terraform apply -target=aws_ecr_repository.resume_agent -target=aws_ecr_lifecycle_policy.resume_agent
   # Push :latest to the repository URL from `terraform output ecr_repository_url`
   # (GitHub “Deploy to ECR” workflow or local docker buildx).
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
   # Set OPENAI_API_KEY, SESSION_SECRET (optional rotate), GMAIL_*, DASHBOARD_BASE_URL=https://your-hostname, etc.
   sudo docker restart resume-agent
   ```

6. **Smoke test**
   - `https://<hostname>/api/health` (or `http://<EIP>:8000/api/health` if hostname not set yet).

7. **Daily run** (cron on the **host**, not inside the container namespace issues):
   ```cron
   5 14 * * * docker exec resume-agent python -m app.jobs.daily_run >> /var/log/resume-agent-cron.log 2>&1
   ```
   (Adjust time / timezone; container name must match.)

8. **Playwright logins** — exec into the container or use SSM + `docker exec -it resume-agent ...` to run `python scripts/login_once.py <site>` so profiles persist under **`/data/playwright`** on the mounted volume.

## Security notes

- Prefer **SSM Session Manager** over SSH (`ssh_cidr_blocks = []`).
- After Caddy works, **remove 0.0.0.0/0 on port 8000** in the security group (AWS console or Terraform) so only **80/443** are public.
- Rotate **`SESSION_SECRET`** if leaked; it signs session cookies for **all** users.

## When to upgrade

- **RAM pressure** (OOM during scrapes): move to **`t4g.large`** (8 GiB).
- **High availability / zero-downtime deploys**: multiple instances need **RDS or Aurora** (not SQLite) and **S3** for artifacts — different architecture and cost.
