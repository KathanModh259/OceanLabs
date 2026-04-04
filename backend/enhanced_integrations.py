"""
Enhanced Integration System with Best Practices
Includes error handling, retries, monitoring, and automatic fallbacks
"""

import asyncio
import logging
import time
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

import httpx
from integrations import (
    run_post_meeting_integrations,
    send_to_slack_channel,
    create_jira_ticket_oauth,
    create_notion_page,
    MAX_SLACK_BODY_CHARS,
    MAX_JIRA_BODY_CHARS,
    MAX_NOTION_TEXT_CHARS,
    DEFAULT_TIMEOUT_SECONDS
)
from integration_store import list_user_integrations, update_user_integration_config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Enhanced retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 2.0  # seconds
BACKOFF_MULTIPLIER = 2.0

class IntegrationHealthMonitor:
    """Monitor integration health and provide automatic fallbacks"""
    
    def __init__(self):
        self.health_cache = {}
        self.failure_counts = {}
        self.last_success = {}
        
    def record_success(self, provider: str):
        """Record successful integration call"""
        self.health_cache[provider] = {"status": "healthy", "last_check": datetime.now(timezone.utc)}
        self.failure_counts[provider] = 0
        self.last_success[provider] = datetime.now(timezone.utc)
        
    def record_failure(self, provider: str, error: str):
        """Record failed integration call"""
        self.failure_counts[provider] = self.failure_counts.get(provider, 0) + 1
        self.health_cache[provider] = {
            "status": "unhealthy",
            "last_check": datetime.now(timezone.utc),
            "error": error,
            "failure_count": self.failure_counts[provider]
        }
        
    def is_healthy(self, provider: str) -> bool:
        """Check if integration is healthy"""
        health = self.health_cache.get(provider, {"status": "unknown"})
        return health.get("status") == "healthy"
        
    def should_use_fallback(self, provider: str) -> bool:
        """Determine if fallback should be used"""
        return self.failure_counts.get(provider, 0) >= 2

# Global health monitor
health_monitor = IntegrationHealthMonitor()

async def enhanced_send_to_slack(
    token: str, 
    channel_id: str, 
    message: str,
    max_retries: int = MAX_RETRIES
) -> tuple[bool, str]:
    """Enhanced Slack sending with retry logic and error handling"""
    
    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                delay = RETRY_DELAY * (BACKOFF_MULTIPLIER ** (attempt - 1))
                logger.info(f"Slack retry {attempt + 1}/{max_retries + 1} after {delay}s delay")
                await asyncio.sleep(delay)
            
            success, detail = await send_to_slack_channel(token, channel_id, message)
            
            if success:
                health_monitor.record_success("slack")
                return True, "ok"
            else:
                # Check for specific errors and provide helpful messages
                if "not_in_channel" in detail:
                    return False, f"Bot not in channel {channel_id}. Invite bot with: /invite @your-bot-name"
                elif "channel_not_found" in detail:
                    return False, f"Channel {channel_id} not found. Check channel ID."
                elif "invalid_auth" in detail:
                    return False, "Invalid Slack token. Check bot permissions."
                else:
                    health_monitor.record_failure("slack", detail)
                    continue
                    
        except Exception as e:
            health_monitor.record_failure("slack", str(e))
            if attempt == max_retries:
                return False, f"Slack error after {max_retries} retries: {str(e)}"
            continue
    
    return False, f"Slack failed after {max_retries + 1} attempts"

async def enhanced_create_jira_ticket(
    access_token: str,
    cloud_id: str,
    project_key: str,
    summary: str,
    description: str,
    issue_type: str = "Task",
    max_retries: int = MAX_RETRIES
) -> tuple[bool, str]:
    """Enhanced Jira ticket creation with retry logic and error handling"""
    
    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                delay = RETRY_DELAY * (BACKOFF_MULTIPLIER ** (attempt - 1))
                logger.info(f"Jira retry {attempt + 1}/{max_retries + 1} after {delay}s delay")
                await asyncio.sleep(delay)
            
            success, detail = await create_jira_ticket_oauth(
                access_token, cloud_id, project_key, summary, description, issue_type
            )
            
            if success:
                health_monitor.record_success("jira")
                return True, detail
            else:
                # Check for specific errors and provide helpful messages
                if "permission" in detail.lower():
                    return False, f"Permission denied in project {project_key}. Check user permissions."
                elif "project not found" in detail.lower() or "404" in detail:
                    return False, f"Project {project_key} not found. Check project key."
                elif "invalid auth" in detail.lower():
                    return False, "Invalid Jira token. Check OAuth setup."
                else:
                    health_monitor.record_failure("jira", detail)
                    continue
                    
        except Exception as e:
            health_monitor.record_failure("jira", str(e))
            if attempt == max_retries:
                return False, f"Jira error after {max_retries} retries: {str(e)}"
            continue
    
    return False, f"Jira failed after {max_retries + 1} attempts"

async def enhanced_create_notion_page(
    notion_token: str,
    database_id: str | None,
    parent_page_id: str | None,
    title: str,
    content: str,
    title_property_name: str = "Name",
    max_retries: int = MAX_RETRIES
) -> tuple[bool, str]:
    """Enhanced Notion page creation with retry logic and error handling"""
    
    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                delay = RETRY_DELAY * (BACKOFF_MULTIPLIER ** (attempt - 1))
                logger.info(f"Notion retry {attempt + 1}/{max_retries + 1} after {delay}s delay")
                await asyncio.sleep(delay)
            
            success, detail = await create_notion_page(
                notion_token, database_id, parent_page_id, title, content, title_property_name
            )
            
            if success:
                health_monitor.record_success("notion")
                return True, detail
            else:
                # Check for specific errors and provide helpful messages
                if "database not found" in detail.lower():
                    return False, f"Database {database_id} not found. Check database ID."
                elif "parent not found" in detail.lower():
                    return False, f"Parent page {parent_page_id} not found. Check page ID."
                elif "invalid_grant" in detail.lower():
                    return False, "Invalid Notion token. Check integration permissions."
                else:
                    health_monitor.record_failure("notion", detail)
                    continue
                    
        except Exception as e:
            health_monitor.record_failure("notion", str(e))
            if attempt == max_retries:
                return False, f"Notion error after {max_retries} retries: {str(e)}"
            continue
    
    return False, f"Notion failed after {max_retries + 1} attempts"

async def enhanced_dispatch_post_meeting_integrations(
    title: str,
    platform: str,
    language: str,
    summary: str,
    transcript: str,
    participants: list[str] | None,
    output_filename: str | None,
    requester_user_id: str | None = None,
    enable_fallbacks: bool = True
) -> dict:
    """Enhanced integration dispatch with best practices"""
    
    start_time = time.time()
    logger.info(f"Starting enhanced integration dispatch for meeting: {title}")
    
    result = {
        "slack": "skipped",
        "jira": "skipped", 
        "notion": "skipped",
        "warnings": [],
        "health_status": {},
        "execution_time": 0,
        "fallbacks_used": []
    }
    
    # Get user connections
    safe_requester_user_id = (requester_user_id or "").strip() or None
    user_connections = list_user_integrations(safe_requester_user_id) if safe_requester_user_id else {}
    
    # Enhanced message formatting
    digest_message = f"""📋 **Smart Meeting Notes Update**

🎯 **Title:** {title or 'Untitled Meeting'}
🌐 **Platform:** {platform or 'unknown'}
🗣️ **Language:** {language or 'Auto'}
👥 **Participants:** {', '.join(participants[:8]) if participants else 'Not detected'}
📁 **Output File:** {output_filename or 'N/A'}

📝 **Summary:**
{summary[:MAX_SLACK_BODY_CHARS]}{'...' if len(summary) > MAX_SLACK_BODY_CHARS else ''}"""

    # Enhanced Jira description
    jira_description = f"""h2. Meeting Details

*Title:* {title or 'Untitled Meeting'}
*Platform:* {platform or 'unknown'}
*Language:* {language or 'Auto'}
*Participants:* {', '.join(participants) if participants else 'Not detected'}
*Output File:* {output_filename or 'N/A'}

h2. AI-Generated Summary

{summary}

h2. Full Transcript

{transcript[:MAX_JIRA_BODY_CHARS]}{'...' if len(transcript) > MAX_JIRA_BODY_CHARS else ''}"""

    # Enhanced Notion content
    notion_title = f"📋 Meeting Notes: {title or 'Untitled Meeting'}"
    notion_content = f"""# 📋 Meeting Details

**Title:** {title or 'Untitled Meeting'}
**Platform:** {platform or 'unknown'}
**Language:** {language or 'Auto'}
**Participants:** {', '.join(participants) if participants else 'Not detected'}
**Output File:** {output_filename or 'N/A'}

---

# 📝 AI-Generated Summary

{summary}

---

# 📄 Full Transcript

{transcript[:MAX_JIRA_BODY_CHARS]}{'...' if len(transcript) > MAX_JIRA_BODY_CHARS else ''}"""

    # Process user OAuth connections first
    if safe_requester_user_id:
        # Enhanced Slack integration
        slack_connection = user_connections.get("slack")
        if slack_connection:
            slack_config = slack_connection.get("config", {})
            slack_token = slack_connection.get("access_token", "")
            slack_channel_id = slack_config.get("channel_id", "").strip()
            
            if slack_token and slack_channel_id:
                success, detail = await enhanced_send_to_slack(slack_token, slack_channel_id, digest_message)
                result["slack"] = "sent" if success else "failed"
                result["health_status"]["slack"] = health_monitor.health_cache.get("slack", {})
                if not success:
                    result["warnings"].append(f"Slack: {detail}")
            else:
                result["warnings"].append("Slack connected but channel_id missing")
        
        # Enhanced Jira integration
        jira_connection = user_connections.get("jira")
        if jira_connection:
            jira_config = jira_connection.get("config", {})
            jira_access_token = jira_connection.get("access_token", "")
            jira_cloud_id = jira_config.get("cloud_id", "").strip()
            jira_project_key = jira_config.get("project_key", "").strip()
            jira_issue_type = jira_config.get("issue_type", "Task").strip() or "Task"
            
            if jira_access_token and jira_cloud_id and jira_project_key:
                success, detail = await enhanced_create_jira_ticket(
                    jira_access_token, jira_cloud_id, jira_project_key,
                    f"Meeting Notes: {title or 'Untitled Meeting'}",
                    jira_description, jira_issue_type
                )
                result["jira"] = f"created:{detail}" if success else "failed"
                result["health_status"]["jira"] = health_monitor.health_cache.get("jira", {})
                if not success:
                    result["warnings"].append(f"Jira: {detail}")
            else:
                result["warnings"].append("Jira connected but cloud_id/project_key missing")
        
        # Enhanced Notion integration
        notion_connection = user_connections.get("notion")
        if notion_connection:
            notion_config = notion_connection.get("config", {})
            notion_token = notion_connection.get("access_token", "")
            notion_database_id = notion_config.get("database_id", "").strip()
            notion_parent_page_id = notion_config.get("parent_page_id", "").strip()
            notion_title_property = notion_config.get("title_property", "Name").strip() or "Name"
            
            if notion_token and (notion_database_id or notion_parent_page_id):
                success, detail = await enhanced_create_notion_page(
                    notion_token, notion_database_id, notion_parent_page_id,
                    notion_title, notion_content, notion_title_property
                )
                result["notion"] = f"created:{detail}" if success else "failed"
                result["health_status"]["notion"] = health_monitor.health_cache.get("notion", {})
                if not success:
                    result["warnings"].append(f"Notion: {detail}")
            else:
                result["warnings"].append("Notion connected but database_id/parent_page_id missing")
    
    # Fallback to environment variables if enabled
    if enable_fallbacks and not safe_requester_user_id:
        import os
        
        # Check if we should use fallbacks based on health
        use_slack_fallback = not health_monitor.should_use_fallback("slack")
        use_jira_fallback = not health_monitor.should_use_fallback("jira") 
        use_notion_fallback = not health_monitor.should_use_fallback("notion")
        
        if use_slack_fallback:
            slack_token = os.environ.get("SLACK_BOT_TOKEN") or os.environ.get("SLACK_TOKEN", "").strip()
            slack_channel_id = os.environ.get("SLACK_CHANNEL_ID", "").strip()
            
            if slack_token and slack_channel_id:
                success, detail = await enhanced_send_to_slack(slack_token, slack_channel_id, digest_message)
                result["slack"] = "sent" if success else "failed"
                if success:
                    result["fallbacks_used"].append("slack")
                elif not success:
                    result["warnings"].append(f"Slack fallback: {detail}")
        
        if use_jira_fallback:
            jira_url = os.environ.get("JIRA_BASE_URL", "").strip()
            jira_email = os.environ.get("JIRA_EMAIL", "").strip()
            jira_token = os.environ.get("JIRA_API_TOKEN", "").strip()
            jira_project_key = os.environ.get("JIRA_PROJECT_KEY", "").strip()
            
            if jira_url and jira_email and jira_token and jira_project_key:
                from integrations import create_jira_ticket
                success, detail = await create_jira_ticket(
                    jira_url, jira_email, jira_token, jira_project_key,
                    f"Meeting Notes: {title or 'Untitled Meeting'}",
                    jira_description
                )
                result["jira"] = f"created:{detail}" if success else "failed"
                if success:
                    result["fallbacks_used"].append("jira")
                elif not success:
                    result["warnings"].append(f"Jira fallback: {detail}")
        
        if use_notion_fallback:
            notion_token = os.environ.get("NOTION_TOKEN") or os.environ.get("NOTION_API_TOKEN", "").strip()
            notion_database_id = os.environ.get("NOTION_DATABASE_ID", "").strip()
            notion_parent_page_id = os.environ.get("NOTION_PARENT_PAGE_ID", "").strip()
            
            if notion_token and (notion_database_id or notion_parent_page_id):
                success, detail = await enhanced_create_notion_page(
                    notion_token, notion_database_id, notion_parent_page_id,
                    notion_title, notion_content
                )
                result["notion"] = f"created:{detail}" if success else "failed"
                if success:
                    result["fallbacks_used"].append("notion")
                elif not success:
                    result["warnings"].append(f"Notion fallback: {detail}")
    
    # Calculate execution time
    result["execution_time"] = round(time.time() - start_time, 2)
    
    # Log results
    logger.info(f"Integration dispatch completed in {result['execution_time']}s")
    logger.info(f"Results: Slack={result['slack']}, Jira={result['jira']}, Notion={result['notion']}")
    
    if result["warnings"]:
        logger.warning(f"Warnings: {'; '.join(result['warnings'])}")
    
    if result["fallbacks_used"]:
        logger.info(f"Fallbacks used: {', '.join(result['fallbacks_used'])}")
    
    return result

def run_enhanced_integrations(**kwargs) -> dict:
    """Wrapper function for enhanced integrations"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(enhanced_dispatch_post_meeting_integrations(**kwargs))
    
    # Fallback for environments without asyncio running
    import threading
    holder = {}
    errors = {}
    
    def worker():
        try:
            holder["value"] = asyncio.run(enhanced_dispatch_post_meeting_integrations(**kwargs))
        except Exception as exc:
            errors["error"] = exc
    
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join()
    
    if "error" in errors:
        raise errors["error"]
    
    return holder.get("value", {
        "slack": "skipped", "jira": "skipped", "notion": "skipped",
        "warnings": [], "health_status": {}, "execution_time": 0, "fallbacks_used": []
    })

def get_integration_health_status() -> dict:
    """Get current health status of all integrations"""
    return {
        "health_cache": health_monitor.health_cache,
        "failure_counts": health_monitor.failure_counts,
        "last_success": health_monitor.last_success,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

def reset_integration_health(provider: str = None):
    """Reset health monitoring for specific provider or all"""
    if provider:
        health_monitor.health_cache.pop(provider, None)
        health_monitor.failure_counts.pop(provider, None)
        health_monitor.last_success.pop(provider, None)
        logger.info(f"Reset health monitoring for {provider}")
    else:
        health_monitor.health_cache.clear()
        health_monitor.failure_counts.clear()
        health_monitor.last_success.clear()
        logger.info("Reset all health monitoring")
