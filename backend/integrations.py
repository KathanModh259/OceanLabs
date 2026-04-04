import asyncio
import base64
import os
import threading
from typing import Optional

import httpx

from integration_store import list_user_integrations

SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"
NOTION_CREATE_PAGE_URL = "https://api.notion.com/v1/pages"
DEFAULT_TIMEOUT_SECONDS = 20.0
MAX_SLACK_BODY_CHARS = 2800
MAX_JIRA_BODY_CHARS = 12000
MAX_NOTION_TEXT_CHARS = 1900
MAX_NOTION_BLOCKS = 80


def truncate_text(text: str, limit: int) -> str:
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def build_meeting_digest(
    title: str,
    platform: str,
    language: str,
    summary: str,
    participants: list[str] | None,
    output_filename: str | None,
) -> str:
    participant_text = ", ".join(participants[:8]) if participants else "Not detected"
    brief_summary = truncate_text(summary or "No summary available.", MAX_SLACK_BODY_CHARS)

    return (
        "Smart Meeting Notes Update\n"
        f"Title: {title or 'Untitled Meeting'}\n"
        f"Platform: {platform or 'unknown'}\n"
        f"Language: {language or 'Auto'}\n"
        f"Participants: {participant_text}\n"
        f"Output File: {output_filename or 'N/A'}\n\n"
        f"Summary:\n{brief_summary}"
    )


def jira_adf_description(text: str) -> dict:
    safe_text = truncate_text(text or "No details provided.", MAX_JIRA_BODY_CHARS)
    paragraphs = [line for line in safe_text.splitlines() if line.strip()]
    if not paragraphs:
        paragraphs = ["No details provided."]

    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": line}],
            }
            for line in paragraphs
        ],
    }


def split_for_notion(text: str, chunk_size: int = MAX_NOTION_TEXT_CHARS) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []

    chunks: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue

        while len(line) > chunk_size:
            chunks.append(line[:chunk_size])
            line = line[chunk_size:]
        chunks.append(line)

    return chunks


def notion_paragraph_blocks(text: str) -> list[dict]:
    chunks = split_for_notion(text)
    blocks = []
    for chunk in chunks[:MAX_NOTION_BLOCKS]:
        blocks.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {"content": chunk},
                        }
                    ]
                },
            }
        )
    return blocks


async def send_to_slack(webhook_url: str, message: str) -> tuple[bool, str]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
        payload = {"text": message}
        response = await client.post(webhook_url, json=payload)
        if response.status_code in {200, 201}:
            return True, "ok"
        return False, f"HTTP {response.status_code}: {response.text[:300]}"


async def send_to_slack_channel(token: str, channel_id: str, message: str) -> tuple[bool, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    payload = {
        "channel": channel_id,
        "text": message,
        "mrkdwn": False,
    }

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
        response = await client.post(SLACK_POST_MESSAGE_URL, headers=headers, json=payload)

    if response.status_code != 200:
        return False, f"HTTP {response.status_code}: {response.text[:300]}"

    data = response.json()
    if data.get("ok"):
        return True, "ok"

    return False, data.get("error", "unknown_slack_error")


async def create_jira_ticket(
    jira_url: str,
    username: str,
    api_token: str,
    project_key: str,
    summary: str,
    description: str,
    issue_type: str = "Task",
) -> tuple[bool, str]:
    jira_url = (jira_url or "").rstrip("/")
    credentials = base64.b64encode(f"{username}:{api_token}".encode("utf-8")).decode("ascii")
    headers = {
        "Authorization": f"Basic {credentials}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    payload_v3 = {
        "fields": {
            "project": {"key": project_key},
            "summary": truncate_text(summary or "Meeting Summary", 240),
            "description": jira_adf_description(description),
            "issuetype": {"name": issue_type or "Task"},
        }
    }

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
        response = await client.post(f"{jira_url}/rest/api/3/issue", headers=headers, json=payload_v3)

        if response.status_code == 201:
            issue_key = response.json().get("key", "created")
            return True, issue_key

        # Fallback for Jira setups still accepting plain text via v2.
        payload_v2 = {
            "fields": {
                "project": {"key": project_key},
                "summary": truncate_text(summary or "Meeting Summary", 240),
                "description": truncate_text(description or "", MAX_JIRA_BODY_CHARS),
                "issuetype": {"name": issue_type or "Task"},
            }
        }
        fallback = await client.post(f"{jira_url}/rest/api/2/issue", headers=headers, json=payload_v2)

    if fallback.status_code == 201:
        issue_key = fallback.json().get("key", "created")
        return True, issue_key

    return False, f"HTTP {fallback.status_code}: {fallback.text[:300]}"


async def create_jira_ticket_oauth(
    access_token: str,
    cloud_id: str,
    project_key: str,
    summary: str,
    description: str,
    issue_type: str = "Task",
) -> tuple[bool, str]:
    if not access_token or not cloud_id or not project_key:
        return False, "missing_jira_oauth_fields"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    payload = {
        "fields": {
            "project": {"key": project_key},
            "summary": truncate_text(summary or "Meeting Summary", 240),
            "description": jira_adf_description(description),
            "issuetype": {"name": issue_type or "Task"},
        }
    }

    endpoint = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue"

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
        response = await client.post(endpoint, headers=headers, json=payload)

    if response.status_code == 201:
        issue_key = response.json().get("key", "created")
        return True, issue_key

    return False, f"HTTP {response.status_code}: {response.text[:300]}"


def _connection_config(connection: Optional[dict]) -> dict:
    if not connection:
        return {}
    value = connection.get("config")
    if isinstance(value, dict):
        return value
    return {}


async def dispatch_post_meeting_integrations(
    title: str,
    platform: str,
    language: str,
    summary: str,
    transcript: str,
    participants: list[str] | None,
    output_filename: str | None,
    requester_user_id: str | None = None,
) -> dict:
    result = {
        "slack": "skipped",
        "jira": "skipped",
        "notion": "skipped",
        "warnings": [],
    }

    digest_message = build_meeting_digest(
        title=title,
        platform=platform,
        language=language,
        summary=summary,
        participants=participants,
        output_filename=output_filename,
    )

    safe_requester_user_id = (requester_user_id or "").strip() or None
    user_connections = list_user_integrations(safe_requester_user_id) if safe_requester_user_id else {}

    jira_description = (
        f"Meeting Title: {title or 'Untitled Meeting'}\n"
        f"Platform: {platform or 'unknown'}\n"
        f"Language: {language or 'Auto'}\n"
        f"Participants: {', '.join(participants) if participants else 'Not detected'}\n"
        f"Output File: {output_filename or 'N/A'}\n\n"
        f"Summary:\n{summary or 'No summary available.'}\n\n"
        f"Transcript:\n{truncate_text(transcript or '', MAX_JIRA_BODY_CHARS)}"
    )

    notion_title = f"Meeting Notes: {title or 'Untitled Meeting'}"
    notion_content = (
        f"Meeting Title: {title or 'Untitled Meeting'}\n"
        f"Platform: {platform or 'unknown'}\n"
        f"Language: {language or 'Auto'}\n"
        f"Participants: {', '.join(participants) if participants else 'Not detected'}\n"
        f"Output File: {output_filename or 'N/A'}\n\n"
        f"Summary:\n{summary or 'No summary available.'}\n\n"
        f"Transcript:\n{truncate_text(transcript or '', MAX_JIRA_BODY_CHARS)}"
    )

    if safe_requester_user_id:
        slack_connection = user_connections.get("slack")
        slack_config = _connection_config(slack_connection)
        slack_token = (slack_connection or {}).get("access_token") or ""
        slack_channel_id = (slack_config.get("channel_id") or "").strip()

        if slack_token and slack_channel_id:
            ok, detail = await send_to_slack_channel(slack_token, slack_channel_id, digest_message)
            result["slack"] = "sent" if ok else "failed"
            if not ok:
                result["warnings"].append(f"Slack API error: {detail}")
        elif slack_token and not slack_channel_id:
            result["warnings"].append("Slack is connected but no channel_id is configured for this user.")

        jira_connection = user_connections.get("jira")
        jira_config = _connection_config(jira_connection)
        jira_access_token = (jira_connection or {}).get("access_token") or ""
        jira_cloud_id = (jira_config.get("cloud_id") or "").strip()
        jira_project_key = (jira_config.get("project_key") or "").strip()
        jira_issue_type = (jira_config.get("issue_type") or "Task").strip() or "Task"

        if jira_access_token and jira_cloud_id and jira_project_key:
            ok, detail = await create_jira_ticket_oauth(
                access_token=jira_access_token,
                cloud_id=jira_cloud_id,
                project_key=jira_project_key,
                summary=f"Meeting Notes: {title or 'Untitled Meeting'}",
                description=jira_description,
                issue_type=jira_issue_type,
            )
            result["jira"] = f"created:{detail}" if ok else "failed"
            if not ok:
                result["warnings"].append(f"Jira error: {detail}")
        elif jira_access_token and (not jira_cloud_id or not jira_project_key):
            result["warnings"].append("Jira is connected but cloud_id/project_key is missing for this user.")

        notion_connection = user_connections.get("notion")
        notion_config = _connection_config(notion_connection)
        notion_token = (notion_connection or {}).get("access_token") or ""
        notion_database_id = (notion_config.get("database_id") or "").strip()
        notion_parent_page_id = (notion_config.get("parent_page_id") or "").strip()
        notion_title_property = (notion_config.get("title_property") or "Name").strip() or "Name"

        if notion_token and (notion_database_id or notion_parent_page_id):
            ok, detail = await create_notion_page(
                notion_token=notion_token,
                database_id=notion_database_id or None,
                parent_page_id=notion_parent_page_id or None,
                title=notion_title,
                content=notion_content,
                title_property_name=notion_title_property,
            )

            result["notion"] = f"created:{detail}" if ok else "failed"
            if not ok:
                result["warnings"].append(f"Notion error: {detail}")
        elif notion_token and not (notion_database_id or notion_parent_page_id):
            result["warnings"].append(
                "Notion is connected but database_id or parent_page_id is missing for this user."
            )
    else:
        slack_webhook_url = (os.environ.get("SLACK_WEBHOOK_URL") or "").strip()
        slack_token = (os.environ.get("SLACK_BOT_TOKEN") or os.environ.get("SLACK_TOKEN") or "").strip()
        slack_channel_id = (os.environ.get("SLACK_CHANNEL_ID") or "").strip()

        if slack_webhook_url:
            ok, detail = await send_to_slack(slack_webhook_url, digest_message)
            result["slack"] = "sent" if ok else "failed"
            if not ok:
                result["warnings"].append(f"Slack webhook error: {detail}")
        elif slack_token and slack_channel_id:
            ok, detail = await send_to_slack_channel(slack_token, slack_channel_id, digest_message)
            result["slack"] = "sent" if ok else "failed"
            if not ok:
                result["warnings"].append(f"Slack API error: {detail}")
        elif slack_token and not slack_channel_id:
            result["warnings"].append("Slack token found but SLACK_CHANNEL_ID is missing.")

        jira_url = (os.environ.get("JIRA_BASE_URL") or "").strip()
        jira_email = (os.environ.get("JIRA_EMAIL") or "").strip()
        jira_token = (os.environ.get("JIRA_API_TOKEN") or "").strip()
        jira_project_key = (os.environ.get("JIRA_PROJECT_KEY") or "").strip()
        jira_issue_type = (os.environ.get("JIRA_ISSUE_TYPE") or "Task").strip() or "Task"

        if jira_url and jira_email and jira_token and jira_project_key:
            ok, detail = await create_jira_ticket(
                jira_url=jira_url,
                username=jira_email,
                api_token=jira_token,
                project_key=jira_project_key,
                summary=f"Meeting Notes: {title or 'Untitled Meeting'}",
                description=jira_description,
                issue_type=jira_issue_type,
            )
            result["jira"] = f"created:{detail}" if ok else "failed"
            if not ok:
                result["warnings"].append(f"Jira error: {detail}")
        elif jira_token and (not jira_url or not jira_email or not jira_project_key):
            result["warnings"].append(
                "Jira token found but JIRA_BASE_URL, JIRA_EMAIL, or JIRA_PROJECT_KEY is missing."
            )

        notion_token = (os.environ.get("NOTION_TOKEN") or os.environ.get("NOTION_API_TOKEN") or "").strip()
        notion_database_id = (os.environ.get("NOTION_DATABASE_ID") or "").strip()
        notion_parent_page_id = (os.environ.get("NOTION_PARENT_PAGE_ID") or "").strip()
        notion_title_property = (os.environ.get("NOTION_TITLE_PROPERTY") or "Name").strip() or "Name"

        if notion_token and (notion_database_id or notion_parent_page_id):
            ok, detail = await create_notion_page(
                notion_token=notion_token,
                database_id=notion_database_id or None,
                parent_page_id=notion_parent_page_id or None,
                title=notion_title,
                content=notion_content,
                title_property_name=notion_title_property,
            )

            result["notion"] = f"created:{detail}" if ok else "failed"
            if not ok:
                result["warnings"].append(f"Notion error: {detail}")
        elif notion_token and not (notion_database_id or notion_parent_page_id):
            result["warnings"].append(
                "Notion token found but NOTION_DATABASE_ID or NOTION_PARENT_PAGE_ID is missing."
            )

    return result


def run_post_meeting_integrations(**kwargs) -> dict:
    async_call = dispatch_post_meeting_integrations(**kwargs)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(async_call)

    holder: dict = {}
    errors: dict = {}

    def worker():
        try:
            holder["value"] = asyncio.run(async_call)
        except Exception as exc:  # noqa: BLE001
            errors["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join()

    if "error" in errors:
        raise errors["error"]

    return holder.get("value", {"slack": "skipped", "jira": "skipped", "notion": "skipped", "warnings": []})


async def create_notion_page(
    notion_token: str,
    database_id: str | None,
    parent_page_id: str | None,
    title: str,
    content: str,
    title_property_name: str = "Name",
) -> tuple[bool, str]:
    if not database_id and not parent_page_id:
        return False, "missing_notion_parent"

    parent_payload = {"database_id": database_id} if database_id else {"page_id": parent_page_id}

    properties = {}
    if database_id:
        properties[title_property_name] = {
            "title": [
                {
                    "type": "text",
                    "text": {"content": truncate_text(title or "Meeting Notes", 240)},
                }
            ]
        }

    blocks = notion_paragraph_blocks(content)
    if not blocks:
        blocks = notion_paragraph_blocks("No meeting details were generated.")

    notion_version = (os.environ.get("NOTION_VERSION") or "2022-06-28").strip() or "2022-06-28"

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
        headers = {
            "Authorization": f"Bearer {notion_token}",
            "Content-Type": "application/json",
            "Notion-Version": notion_version,
        }
        payload = {
            "parent": parent_payload,
            "children": blocks,
        }

        if properties:
            payload["properties"] = properties

        response = await client.post(NOTION_CREATE_PAGE_URL, headers=headers, json=payload)

    if response.status_code in {200, 201}:
        response_data = response.json()
        page_id = response_data.get("id", "created")
        return True, page_id

    return False, f"HTTP {response.status_code}: {response.text[:300]}"
