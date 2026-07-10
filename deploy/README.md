# Deployment artifacts

systemd units for the daily pipeline (doc 12 §2). These run on the VPS, not in dev.

## Install

```bash
sudo cp deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now seismo-collect-fast.timer
systemctl list-timers 'seismo-*'          # verify next-run times
journalctl -u seismo-collect-fast --since today   # logs (journald is the log store)
```

Secrets live in `/etc/seismograph/env` (`chmod 600`, root-owned), loaded via `EnvironmentFile`.
Required for full collection: `SEISMO_DATABASE_URL`, `SEISMO_GITHUB_TOKEN` (the GitHub Search
API is 403-rate-limited without a token). Everything else has safe defaults.

Timers added per stage:
- **Stage 1:** `seismo-collect-fast` (github, hn, arxiv — daily 05:30 UTC).
- Later stages add `seismo-collect-usage`, `seismo-collect-slow`, and `seismo-pipeline`
  (resolve → snapshot → score → …), plus `seismo-backup` and `seismo-doctor` (doc 12).
