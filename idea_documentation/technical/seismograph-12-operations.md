# Seismograph — 12 Deployment & Operations

*Implements idea-spec §10 constraints (personal infrastructure, public data only) and failure-mode guards #4 (collector rot) and general survivability. Boring by design.*

> **Amended by doc 13:** `seismo doctor` (§3) gains three checks — **A-4** tracking-tier budget (active-tier count × per-source request cost < GitHub ceiling headroom), **A-12** `pending` vs `failed` checkpoint counts (alert if `pending` >48h), and the A-2 graph-purity assertion in the health suite. The daily `run-daily` sequence (§2) inserts `retier` before `snapshot`, and the weekly `collect-slow` timer now also carries the v1 pricing watcher (A-5).

---

## DR-12.1 — Caddy over nginx
Automatic HTTPS, 10-line config, basic_auth built in. nginx wins nothing here. No dissent.

## DR-12.2 — Backups: nightly logical dump + restore drills
At this data volume (GBs, not TBs), `pg_dump` piped to zstd, rclone'd to a Hetzner Storage Box, 30-day retention, beats WAL archiving complexity. **Adversarial Reviewer:** a backup that has never been restored is a hope, not a backup. **Verdict:** quarterly restore drill into a scratch database is a checklist item in the calibration ritual (doc 09 §4). Raw-event immutability means a restore loses at most one day of collectable-again data.

---

## 1. Server provisioning (Hetzner CX32 · Ubuntu 24.04)

```bash
# as root, once
adduser seismo && usermod -aG sudo seismo   # then key-only SSH, disable root+password auth
apt update && apt install -y postgresql-16 caddy ufw fail2ban unattended-upgrades zstd rclone git
ufw allow OpenSSH && ufw allow 80,443/tcp && ufw enable
# Node LTS (nodesource) for the dashboard; uv per official installer for user seismo
```
App layout: code at `/opt/seismograph` (git clone, owned by `seismo`), env at `/etc/seismograph/env` (`chmod 600`, root-owned), dumps staging at `/var/backups/seismograph`.

## 2. systemd units (patterns — one service+timer per pipeline stage group)

```ini
# /etc/systemd/system/seismo-pipeline.service
[Unit]
Description=Seismograph daily pipeline
After=postgresql.service
[Service]
Type=oneshot
User=seismo
EnvironmentFile=/etc/seismograph/env
WorkingDirectory=/opt/seismograph
ExecStart=/home/seismo/.local/bin/uv run seismo run-daily
TimeoutStartSec=2h
```
```ini
# /etc/systemd/system/seismo-pipeline.timer
[Timer]
OnCalendar=*-*-* 06:15 UTC
Persistent=true          # catches up after downtime
[Install]
WantedBy=timers.target
```
`run-daily` = collect(fast) → collect(usage) → resolve → snapshot → score → comprehend → (Mondays: gate → brief drafts) → changes. Each step already idempotent, so `Persistent=true` is safe. Long-running services: `seismo-api` (uvicorn) and `seismo-dashboard` (`next start`), both `Restart=on-failure`, behind Caddy.

```
# /etc/caddy/Caddyfile
seismo.example.com {
    basic_auth { nikola <bcrypt-hash> }
    handle /api/* { reverse_proxy 127.0.0.1:8000 }
    handle       { reverse_proxy 127.0.0.1:3000 }
}
```

## 3. Health: `seismo doctor` + external pinger

`doctor` (also a timer, hourly; and the `/health` endpoint) checks and reports one green/red table:
- **Collector silence:** any source with 0 new events for >2× its cadence (the calm-that-is-actually-silence failure)
- Last pipeline run ok + duration trend (creeping slowness = upstream trouble)
- Merge-queue depth (>50 = curation debt)
- LLM spend vs monthly ceiling; failed checkpoint calls
- Exposure-map staleness (>120 days per doc 08 §5)
- Backup age (<26 h) and last restore-drill date
Each timer additionally pings a **healthchecks.io** check on success — dead-man's-switch alerting to email/Telegram costs nothing and catches "the whole box is down," which self-reporting cannot.

## 4. Logging & observability

journald is the log store: `journalctl -u seismo-pipeline --since today`. Python logging → stdout, structured-ish (`key=value`), no log files to rotate. Sentry (free tier) optional for the API + checkpoints — decide at Stage 10, not before. No Prometheus/Grafana: `doctor` + healthchecks.io is the right observability *size* for one box and one operator.

## 5. Deploy runbook (also the disaster-recovery script, ~10 lines)

```bash
cd /opt/seismograph && git pull
uv sync --frozen
uv run alembic upgrade head
cd dashboard && npm ci && npm run build && cd ..
sudo systemctl restart seismo-api seismo-dashboard
uv run seismo doctor
```
Rollback = `git checkout <prev-tag>` + same steps (migrations are forward-only; write them additive). Fresh-box recovery = §1 + restore latest dump + this runbook; target <2 h, verified once in the Stage 10 drill.

## 6. Backups

```bash
# seismo-backup.service (timer 03:30 UTC)
pg_dump -Fc seismograph | zstd > /var/backups/seismograph/$(date +%F).dump.zst
rclone copy /var/backups/seismograph storagebox:seismograph/ --max-age 24h
find /var/backups/seismograph -mtime +7 -delete   # local 7d; remote pruned to 30d via rclone
```
`exposure_map/` and all config-as-code need no backup beyond git (pushed to a private remote).

## 7. Security & legitimacy baseline
- Key-only SSH, fail2ban defaults, unattended-upgrades on, ufw as above
- Secrets only in `/etc/seismograph/env`; never in git, never in journald (no secret printing)
- All collectors identify themselves (UA + contact) and honor limits — idea-spec §5 politeness is an ops guarantee too
- Public data only; nothing on this box touches employer systems or credentials (idea-spec §10, restated as an operational rule)

## 8. Definition of done (Stage 10)
- [ ] All timers green 14 consecutive days; `Persistent=true` verified by a deliberate reboot
- [ ] healthchecks.io wired on pipeline, backup, doctor
- [ ] Restore drill performed; fresh-box recovery time recorded
- [ ] Runbook tested by a real deploy; monthly cost confirmed ≈ €25
