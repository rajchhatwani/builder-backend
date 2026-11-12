# Scheduling the periodic jobs

One process runs everything: `python -m app.jobs.scheduler` (reports every minute, idle-workspace sweep and usage-gauge
reconcile every hour; `BUILDER_SCHEDULER_REPORT_SECONDS`, `BUILDER_SCHEDULER_SWEEP_SECONDS`, floor 5 s). A failing job is
logged and retried on its next tick. Last-run status is on the admin Operations page.

- docker compose: the `scheduler` service in `docker-compose.yml` (`restart: unless-stopped`).
- systemd: `deploy/systemd/builder-scheduler.service` (copy, set `/etc/builder/scheduler.env`, `systemctl enable --now`).
- cron alternative (no long-lived process): `* * * * * python -m app.jobs.report_scheduler` and
  `0 * * * * python -m app.jobs.idle_sweep`.
Celery is not used.
