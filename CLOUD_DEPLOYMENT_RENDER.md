# Cloud Deployment Guide (Website + API)

This setup deploys:
- Frontend React app as a public website
- Backend FastAPI as a public API

Using Render Blueprint (`render.yaml`) in this repo.

## 1) Push Repo To GitHub

Render deploys from GitHub, so make sure your latest code is pushed.

## 2) Create Render Blueprint Deploy

1. Open Render dashboard.
2. Click **New** -> **Blueprint**.
3. Connect your GitHub repo.
4. Select branch and deploy.

Render will create two services from [render.yaml](render.yaml):
- `oceanlabs-api-1281` (backend, Docker)
- `oceanlabs-web` (frontend static site)

## 3) Set Backend Environment Variables

Use [backend/.env.cloud.example](backend/.env.cloud.example) as reference and set these in Render for `oceanlabs-api-1281`:

- `ENVIRONMENT=production`
- `FRONTEND_ORIGINS=https://<your-frontend-domain>`
- `BACKEND_PUBLIC_BASE_URL=https://<your-backend-domain>`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_ANON_KEY`
- OAuth vars for Slack/Jira/Notion if used

## 4) Set Frontend Environment Variables

Use [frontend/.env.production.example](frontend/.env.production.example) as reference and set these in Render for `oceanlabs-web`:

- `VITE_SUPABASE_URL`
- `VITE_SUPABASE_ANON_KEY`
- `VITE_API_BASE_URL=https://<your-backend-domain>`

## 5) Update OAuth Callback URLs

In Slack/Jira/Notion developer consoles, set callback URLs to your deployed backend URL:

- `https://<your-backend-domain>/api/integrations/oauth/slack/callback`
- `https://<your-backend-domain>/api/integrations/oauth/jira/callback`
- `https://<your-backend-domain>/api/integrations/oauth/notion/callback`

## 6) Verify Deployment

After deployment:

1. Open frontend URL and log in.
2. Check backend health: `https://<your-backend-domain>/api/health`
3. Test integrations page.
4. Start a test meeting event.

## Important Runtime Note

This project includes browser/audio automation paths that are Windows-loopback oriented (`pyaudiowpatch`).

On Linux cloud containers, dashboard/API/integrations work, but full desktop-like loopback recording behavior may differ.

For strict 24x7 meeting-capture parity, keep recorder backend on an always-on Windows VM and still host the frontend publicly.
