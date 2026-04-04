# OAuth Setup Instructions for Third-Party Integrations

## Overview
Your application already has a complete OAuth implementation for Slack, Jira, and Notion. You just need to configure the environment variables and set up the OAuth apps.

## Step 1: Configure Environment Variables

Add these to your `.env` file in the backend directory:

### Slack OAuth
```
SLACK_OAUTH_CLIENT_ID=your_slack_client_id_here
SLACK_OAUTH_CLIENT_SECRET=your_slack_client_secret_here
SLACK_OAUTH_SCOPES=chat:write,chat:write.public,channels:read,groups:read
SLACK_OAUTH_USER_SCOPES=
```

### Jira OAuth  
```
JIRA_OAUTH_CLIENT_ID=your_jira_client_id_here
JIRA_OAUTH_CLIENT_SECRET=your_jira_client_secret_here
JIRA_OAUTH_SCOPES=write:jira-work read:jira-user offline_access read:me
JIRA_OAUTH_AUDIENCE=api.atlassian.com
```

### Notion OAuth
```
NOTION_OAUTH_CLIENT_ID=your_notion_client_id_here
NOTION_OAUTH_CLIENT_SECRET=your_notion_client_secret_here
NOTION_VERSION=2022-06-28
```

### Supabase Configuration
```
SUPABASE_URL=your_supabase_url_here
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key_here
```

### Backend URLs
```
BACKEND_PUBLIC_BASE_URL=http://localhost:8000
FRONTEND_PUBLIC_BASE_URL=http://localhost:5173
```

## Step 2: Create OAuth Apps

### Slack
1. Go to https://api.slack.com/apps
2. Create New App → From scratch
3. Add OAuth Permissions:
   - `chat:write`
   - `chat:write.public` 
   - `channels:read`
   - `groups:read`
4. Set Redirect URL: `http://localhost:8000/api/integrations/oauth/slack/callback`
5. Copy Client ID and Client Secret

### Jira
1. Go to https://developer.atlassian.com/console/myapps/
2. Create new app → OAuth 2.0
3. Set Callback URL: `http://localhost:8000/api/integrations/oauth/jira/callback`
4. Configure scopes:
   - `write:jira-work`
   - `read:jira-user`
   - `offline_access`
   - `read:me`
5. Copy Client ID and Client Secret

### Notion
1. Go to https://www.notion.so/my-integrations
2. Create new integration
3. Set Redirect URL: `http://localhost:8000/api/integrations/oauth/notion/callback`
4. Copy Client ID and Client Secret

## Step 3: Database Setup

Run the SQL migration in `supabase_integrations_oauth_setup.sql` in your Supabase SQL editor to create the `integration_connections` table.

## Step 4: Test the Integration

1. Start the backend server: `python api_server.py`
2. Start the frontend server
3. Go to Settings/Integrations in your app
4. Click "Connect" for each service to test the OAuth flow

## API Endpoints

- `GET /api/integrations/status` - Check integration status
- `GET /api/integrations/oauth/{provider}/start` - Start OAuth flow
- `GET /api/integrations/oauth/{provider}/callback` - OAuth callback
- `POST /api/integrations/config` - Save integration config
- `POST /api/integrations/disconnect` - Disconnect integration
- `POST /api/integrations/test` - Test integration

## Integration Flow

1. User clicks "Connect" → OAuth flow starts
2. User authorizes the app → Redirect back with code
3. Backend exchanges code for access token
4. Token stored in Supabase with user's configuration
5. Post-meeting integrations automatically use stored tokens

## Troubleshooting

- **"OAuth client ID/secret is missing"** → Check environment variables
- **"OAuth state is invalid or expired"** → Restart OAuth flow
- **"Supabase is not configured"** → Check SUPABASE_URL and keys
- **Integration not working** → Check `/api/integrations/status` endpoint
