"""Out-of-process notifications (email digest today; Slack/webhooks later).

`email.send_digest(jobs, date)` sends an HTML digest via Gmail SMTP using
an App Password. See `.env.example` for the required env vars.
"""
