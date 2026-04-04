# OceanLabs 24x7 Deployment (Windows)

This project uses browser automation + system loopback audio capture.
For reliable production behavior, run backend on an always-on Windows VM.

## Fast Answer: Why automation stops when you close your machine

Your backend/recorder process is currently tied to your local machine/session.
When terminal/session/machine stops, automation stops too.

To make it truly live:
- move backend to a dedicated always-on Windows VM
- run backend as a managed process (service or startup task)
- expose backend over HTTPS (WebSocket support)
- deploy frontend as static app

## Deployment Modes (Choose One)

### Mode A: Windows Service (NSSM)

Use this for strict background operation.

Pros:
- auto-start on boot
- easy restart + service monitoring

Tradeoff:
- if browser automation requires visible desktop/user context, service mode may be less reliable on some hosts.

### Mode B: Startup Task (Interactive User Logon)

Use this when browser automation/login/caption extraction works better with interactive desktop context.

Pros:
- best compatibility for Playwright + meeting UI behavior

Tradeoff:
- needs dedicated auto-logon user session policy on VM

## Files Added for You

- deploy/windows/install-backend-service.ps1
- deploy/windows/uninstall-backend-service.ps1
- deploy/windows/register-backend-startup-task.ps1
- deploy/windows/unregister-backend-startup-task.ps1
- deploy/windows/run-backend.ps1
- deploy/windows/set-power-plan-24x7.ps1
- deploy/windows/go-live-check.ps1
- deploy/Caddyfile.example
- deploy/nginx.conf.example
- backend/.env.example
- frontend/.env.production.example

## 1) Provision VM

Recommended baseline:
- Windows Server 2022 or Windows 11 Pro VM
- 4 vCPU, 16 GB RAM, SSD
- static public IP + domain

## 2) Install Dependencies

- Git
- Python 3.11
- Node.js 20+
- Chrome or Edge

## 3) Deploy Code

```powershell
git clone <your-repo-url> D:\OceanLabs\Language
Set-Location D:\OceanLabs\Language
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
python -m playwright install chromium
```

Frontend build:

```powershell
Set-Location D:\OceanLabs\Language\frontend
npm ci
npm run build
```

## 4) Environment Configuration

- Copy backend/.env.example -> backend/.env and fill real secrets.
- Copy frontend/.env.production.example -> frontend/.env.production and fill values.
- Do not commit real credentials.

Important runtime knobs:
- PLAYWRIGHT_HEADLESS=false (interactive mode)
- PLAYWRIGHT_HEADLESS=true (service mode, no desktop)

## 5) Run Supabase Migrations

Execute in Supabase SQL Editor:
- backend/supabase_user_scope_setup.sql
- backend/supabase_integrations_oauth_setup.sql

## 6) Choose Process Manager

### Option A (NSSM service)

```powershell
Set-Location D:\OceanLabs\Language
.\deploy\windows\install-backend-service.ps1 -ProjectRoot "D:\OceanLabs\Language" -Port 8000
```

Uninstall:

```powershell
.\deploy\windows\uninstall-backend-service.ps1
```

### Option B (Startup task at logon)

```powershell
Set-Location D:\OceanLabs\Language
.\deploy\windows\register-backend-startup-task.ps1 -ProjectRoot "D:\OceanLabs\Language" -Port 8000
```

Remove task:

```powershell
.\deploy\windows\unregister-backend-startup-task.ps1
```

## 7) Keep VM Awake (24x7)

Run once as Administrator:

```powershell
Set-Location D:\OceanLabs\Language
.\deploy\windows\set-power-plan-24x7.ps1
```

## 8) Reverse Proxy + HTTPS

Use one of:
- deploy/Caddyfile.example
- deploy/nginx.conf.example

Must support WebSocket upgrades for:
- /api/recordings/{recording_id}/stream

## 9) Health + Monitoring

Backend health endpoints:
- /api/health
- /api/healthz

Quick local test:

```powershell
Set-Location D:\OceanLabs\Language
.\deploy\windows\go-live-check.ps1 -BaseUrl "http://127.0.0.1:8000"
```

Monitor:
- process alive
- /api/health returns status=ok
- log growth in D:\OceanLabs\Language\logs

## 10) Frontend Go-Live

Deploy frontend static build to your host (Vercel/Netlify/Azure SWA/VM).
Point VITE_API_BASE_URL to your backend public HTTPS URL.

## 11) Security Before Public Release

- rotate all exposed keys/tokens
- use least-privilege credentials
- lock down VM firewall (only required ports)
- enforce HTTPS only

## 12) Scale Plan

Browser-driven recording is compute-heavy.
Start with one recorder VM, then scale horizontally:
- API gateway -> multiple recorder workers
- queue recording jobs
- pin per-session browser resources
