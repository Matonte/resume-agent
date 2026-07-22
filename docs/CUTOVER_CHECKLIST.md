# Local now → AWS when billing is ready

Nothing here **requires** AWS or a payment method. Use the **interim** section daily; when your AWS account can charge (or you attach a card), run the **cutover** section in order.

## Interim: full local use (no cloud)

| Goal | Command / path |
|------|------------------|
| API + UI | `.\scripts\run_local.ps1` or `.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload` |
| Health | http://127.0.0.1:8000/api/health |
| Daily scrape + tailor | `.\.venv\Scripts\python.exe -m app.jobs.daily_run --no-email` (add flags as needed) |
| One-time job site login | `.\.venv\Scripts\python.exe scripts\login_once.py linkedin` (etc.) |
| Config | `data\preferences.yaml` + `.env` (copy from `.env.example`) |
| State on disk | `outputs\` (SQLite + artifacts) and `.playwright\` (cookies) — both gitignored |
| Optional prep stack | [Contact Advisor](https://github.com/Matonte/contact-advisor) (Meeting Advisor + people-intel) — [setup in main README](../README.md#contact-advisor--meeting-advisor-optional) |

**CI/CD without AWS:** Push to GitHub. Workflows run **pytest** and can **build/push the Docker image to GHCR** using `GITHUB_TOKEN` only. No AWS secrets needed.

## Ready for AWS: what to prepare (still $0)

Do these when you have time; they do not bill anything by themselves.

1. **Commit** `aws/terraform/.terraform.lock.hcl` (provider pins for repeatable `terraform apply`).
2. **Copy** `aws/terraform/terraform.tfvars.example` → `terraform.tfvars` (local only; never commit secrets).
3. **Install** [Terraform](https://developer.hashicorp.com/terraform/install) and [AWS CLI](https://docs.aws.amazon.com/cli/) on the machine you’ll use to deploy.
4. **GitHub → Deploy to AWS** (optional until billing): after Terraform, set secret `AWS_ROLE_TO_ASSUME` (OIDC role ARN) and vars `AWS_REGION`, `AWS_ECR_REPOSITORY`, `EC2_INSTANCE_ID` — see [aws/README.md](../aws/README.md).

## Cutover: after AWS can provision resources

Estimated time: **~30–60 minutes** if the image is already in ECR.

1. `aws configure` (or SSO) so `aws sts get-caller-identity` succeeds.
2. `cd aws/terraform && terraform init`
3. **ECR first** (empty repo is OK; avoids a failed first boot):
   ```bash
   terraform apply -target=aws_ecr_repository.resume_agent -target=aws_ecr_lifecycle_policy.resume_agent
   ```
4. Push **`latest`** to that repository (GitHub **Deploy to ECR** workflow, or local `docker buildx build --platform linux/arm64 --push ...`).
5. **Full stack:**
   ```bash
   terraform apply
   ```
   Creates **EC2 (`t4g.large`)**, **RDS MySQL**, EIP, optional Route53, and writes `DATABASE_URL` into instance user-data.
6. Point DNS at the **Elastic IP** (or use Route53 variables in `terraform.tfvars`).
7. **SSM Session Manager** on the instance: edit `/opt/resume-agent/.env`, set `OPENAI_API_KEY`, `DASHBOARD_BASE_URL`, Gmail if needed, optional Contact Advisor URLs, then `docker restart resume-agent`.

Full detail: [aws/README.md](../aws/README.md).

## Cost reminder

**Local:** \$0 (plus your OpenAI usage if enabled).  
**AWS:** starts when you `terraform apply` (EC2 + RDS + EBS + ECR, etc. — roughly **\$65–85/mo** for `t4g.large` + `db.t4g.micro`). Use the [AWS Pricing Calculator](https://calculator.aws/) before the final apply if you want a firm number.
