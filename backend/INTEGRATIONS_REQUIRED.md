# Integration Requirements

This project supports automated post-meeting delivery to Slack, Jira, and Notion.

## Recommended Model (Multi-User)

Use per-user OAuth connections from the Settings page.

### Required OAuth Environment Variables

#### Slack OAuth
- `SLACK_OAUTH_CLIENT_ID`
- `SLACK_OAUTH_CLIENT_SECRET`
- Optional: `SLACK_OAUTH_REDIRECT_URI`
- Optional: `SLACK_OAUTH_SCOPES` (default: `chat:write,chat:write.public,channels:read,groups:read`)

#### Jira OAuth (Atlassian 3LO)
- `JIRA_OAUTH_CLIENT_ID`
- `JIRA_OAUTH_CLIENT_SECRET`
- Optional: `JIRA_OAUTH_REDIRECT_URI`
- Optional: `JIRA_OAUTH_SCOPES` (default: `write:jira-work read:jira-user offline_access read:me`)
- Optional: `JIRA_OAUTH_AUDIENCE` (default: `api.atlassian.com`)

#### Notion OAuth
- `NOTION_OAUTH_CLIENT_ID`
- `NOTION_OAUTH_CLIENT_SECRET`
- Optional: `NOTION_OAUTH_REDIRECT_URI`

### Shared App URLs
- `BACKEND_PUBLIC_BASE_URL` (example: `http://localhost:8000`)
- `FRONTEND_PUBLIC_BASE_URL` (example: `http://localhost:5173`)

## Legacy Fallback (Single-Tenant)

If `requester_user_id` is missing, integrations can still use global env tokens.

## 1. Slack

### Environment Variables
- `SLACK_WEBHOOK_URL` (recommended for simplest setup)
- Or token mode:
- `SLACK_TOKEN` (or `SLACK_BOT_TOKEN`)
- `SLACK_CHANNEL_ID`

### Slack App Permissions (token mode)
- `chat:write`
- Channel access to the target channel

## 2. Jira

### Environment Variables
- `JIRA_API_TOKEN`
- `JIRA_BASE_URL` (example: `https://your-domain.atlassian.net`)
- `JIRA_EMAIL`
- `JIRA_PROJECT_KEY`
- Optional: `JIRA_ISSUE_TYPE` (default: `Task`)

### Jira Requirements
- API token belongs to `JIRA_EMAIL`
- User has create issue permission in `JIRA_PROJECT_KEY`

## 3. Notion

### Environment Variables
- `NOTION_TOKEN` (or `NOTION_API_TOKEN`)
- One of:
- `NOTION_DATABASE_ID`
- `NOTION_PARENT_PAGE_ID`
- Optional: `NOTION_TITLE_PROPERTY` (default: `Name`)
- Optional: `NOTION_VERSION` (default: `2022-06-28`)

### Notion Requirements
- Integration is shared with the target database/page
- If using `NOTION_DATABASE_ID`, verify title property name matches `NOTION_TITLE_PROPERTY`

## 4. API Endpoints You Can Use

### Recording
- `POST /api/start-recording`
- `POST /api/stop-recording/{recording_id}`
- `GET /api/recordings`
- `GET /api/recordings/{recording_id}`

### Integrations (Website Ready)
- `GET /api/integrations/status?user_id=<supabase_user_id>`
- `POST /api/integrations/test`

### OAuth + Config Management
- `GET /api/integrations/oauth/{provider}/start?user_id=<supabase_user_id>&next_url=<frontend_url>`
- `GET /api/integrations/oauth/{provider}/callback`
- `POST /api/integrations/config`
- `POST /api/integrations/disconnect`

## Database Migration

Run both migrations in Supabase SQL Editor:
- `backend/supabase_user_scope_setup.sql`
- `backend/supabase_integrations_oauth_setup.sql`

## Notes
- Integrations are best-effort and non-blocking: recording/notes generation continues even if a target system fails.
- In user-scoped mode, per-user OAuth credentials are used when `requester_user_id` is present.
- Keep secrets in environment variables and secure storage; do not hardcode secrets in source files.
