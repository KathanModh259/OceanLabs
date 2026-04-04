"""
Automatic Integration Fixer
Detects and automatically fixes common integration issues
"""

import asyncio
import os
import re
from typing import Dict, Any, Optional, Tuple
from dotenv import load_dotenv

load_dotenv('.env')

class IntegrationAutoFixer:
    """Automatically detects and fixes integration configuration issues"""
    
    def __init__(self):
        self.fixes_applied = []
        self.issues_found = []
        
    def detect_and_fix_slack_issues(self) -> Dict[str, Any]:
        """Detect and fix Slack integration issues"""
        slack_issues = {
            "issues": [],
            "fixes": [],
            "status": "unknown"
        }
        
        # Check for Slack token
        slack_token = os.environ.get("SLACK_BOT_TOKEN") or os.environ.get("SLACK_TOKEN", "").strip()
        if not slack_token:
            slack_issues["issues"].append("Missing SLACK_BOT_TOKEN or SLACK_TOKEN")
            slack_issues["fixes"].append("Add Slack bot token to environment variables")
        elif not slack_token.startswith("xoxb-"):
            slack_issues["issues"].append("Invalid Slack token format")
            slack_issues["fixes"].append("Token should start with 'xoxb-' for bot tokens")
        
        # Check for channel ID
        channel_id = os.environ.get("SLACK_CHANNEL_ID", "").strip()
        if not channel_id:
            slack_issues["issues"].append("Missing SLACK_CHANNEL_ID")
            slack_issues["fixes"].append("Add Slack channel ID to environment variables")
        elif not re.match(r'^[A-Z0-9]+$', channel_id):
            slack_issues["issues"].append(f"Invalid channel ID format: {channel_id}")
            slack_issues["fixes"].append("Channel ID should be in format like 'C0123456789'")
        
        # Check webhook URL
        webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
        if webhook_url and not webhook_url.startswith("https://hooks.slack.com/"):
            slack_issues["issues"].append("Invalid webhook URL format")
            slack_issues["fixes"].append("Webhook URL should start with 'https://hooks.slack.com/'")
        
        slack_issues["status"] = "healthy" if not slack_issues["issues"] else "needs_fixes"
        return slack_issues
        
    def detect_and_fix_jira_issues(self) -> Dict[str, Any]:
        """Detect and fix Jira integration issues"""
        jira_issues = {
            "issues": [],
            "fixes": [],
            "status": "unknown"
        }
        
        # Check Jira URL
        jira_url = os.environ.get("JIRA_BASE_URL", "").strip()
        if not jira_url:
            jira_issues["issues"].append("Missing JIRA_BASE_URL")
            jira_issues["fixes"].append("Add Jira base URL (e.g., https://your-domain.atlassian.net)")
        elif not jira_url.startswith("https://") and not jira_url.startswith("http://"):
            jira_issues["issues"].append("Invalid Jira URL format")
            jira_issues["fixes"].append("URL should start with http:// or https://")
        elif ".atlassian.net" not in jira_url:
            jira_issues["issues"].append("Invalid Jira domain")
            jira_issues["fixes"].append("URL should be a valid Atlassian domain")
        
        # Check email
        jira_email = os.environ.get("JIRA_EMAIL", "").strip()
        if not jira_email:
            jira_issues["issues"].append("Missing JIRA_EMAIL")
            jira_issues["fixes"].append("Add Jira user email")
        elif "@" not in jira_email or "." not in jira_email.split("@")[1]:
            jira_issues["issues"].append("Invalid email format")
            jira_issues["fixes"].append("Email should be in format user@domain.com")
        
        # Check API token
        jira_token = os.environ.get("JIRA_API_TOKEN", "").strip()
        if not jira_token:
            jira_issues["issues"].append("Missing JIRA_API_TOKEN")
            jira_issues["fixes"].append("Add Jira API token")
        elif len(jira_token) < 20:
            jira_issues["issues"].append("Jira token too short")
            jira_issues["fixes"].append("Jira API tokens are typically longer")
        
        # Check project key
        project_key = os.environ.get("JIRA_PROJECT_KEY", "").strip()
        if not project_key:
            jira_issues["issues"].append("Missing JIRA_PROJECT_KEY")
            jira_issues["fixes"].append("Add Jira project key (e.g., KAN, PROJ)")
        elif not re.match(r'^[A-Z][A-Z0-9]*$', project_key):
            jira_issues["issues"].append(f"Invalid project key format: {project_key}")
            jira_issues["fixes"].append("Project key should be 2-10 uppercase letters/numbers")
        
        jira_issues["status"] = "healthy" if not jira_issues["issues"] else "needs_fixes"
        return jira_issues
        
    def detect_and_fix_notion_issues(self) -> Dict[str, Any]:
        """Detect and fix Notion integration issues"""
        notion_issues = {
            "issues": [],
            "fixes": [],
            "status": "unknown"
        }
        
        # Check Notion token
        notion_token = os.environ.get("NOTION_TOKEN") or os.environ.get("NOTION_API_TOKEN", "").strip()
        if not notion_token:
            notion_issues["issues"].append("Missing NOTION_TOKEN")
            notion_issues["fixes"].append("Add Notion integration token")
        elif not notion_token.startswith("ntn_"):
            notion_issues["issues"].append("Invalid Notion token format")
            notion_issues["fixes"].append("Notion tokens should start with 'ntn_'")
        
        # Check database ID
        database_id = os.environ.get("NOTION_DATABASE_ID", "").strip()
        if database_id:
            if not re.match(r'^[a-f0-9]{32}$', database_id):
                notion_issues["issues"].append(f"Invalid database ID format: {database_id}")
                notion_issues["fixes"].append("Database ID should be 32-character hex string")
        
        # Check parent page ID
        parent_page_id = os.environ.get("NOTION_PARENT_PAGE_ID", "").strip()
        if parent_page_id:
            if not re.match(r'^[a-f0-9]{32}$', parent_page_id):
                notion_issues["issues"].append(f"Invalid parent page ID format: {parent_page_id}")
                notion_issues["fixes"].append("Page ID should be 32-character hex string")
        
        # Check if neither database nor page ID is provided
        if not database_id and not parent_page_id:
            notion_issues["issues"].append("Missing target location")
            notion_issues["fixes"].append("Provide either NOTION_DATABASE_ID or NOTION_PARENT_PAGE_ID")
        
        notion_issues["status"] = "healthy" if not notion_issues["issues"] else "needs_fixes"
        return notion_issues
        
    def generate_slack_invitation_command(self, channel_id: str) -> str:
        """Generate Slack invitation command"""
        return f"To invite your bot to the channel, use: /invite @OceanLabs Meeting Bot\\nOr add bot manually to channel: {channel_id}"
        
    def generate_jira_permission_fix_guide(self, project_key: str, email: str) -> str:
        """Generate Jira permission fix guide"""
        return f"""Jira Permission Fix Guide:

1. Go to: https://charusat-team-f3fjjw3c.atlassian.net/browse/{project_key}
2. Check if you can create issues manually
3. If not, contact your Jira administrator
4. Request permissions: Browse Projects + Create Issues
5. Verify your account {email} has proper access

Alternative: Change JIRA_PROJECT_KEY to a project where you have permissions"""
        
    def generate_notion_access_fix_guide(self, database_id: str = None, parent_page_id: str = None) -> str:
        """Generate Notion access fix guide"""
        target = f"database {database_id}" if database_id else f"page {parent_page_id}"
        return f"""Notion Access Fix Guide:

1. Go to: https://www.notion.so/my-integrations
2. Find your integration and check permissions
3. Ensure it has access to {target}
4. Re-authorize if needed
5. Share the {target} with your integration

For databases: Ensure "Can create pages" is enabled
For pages: Ensure "Can edit" is enabled"""
        
    def run_complete_diagnosis(self) -> Dict[str, Any]:
        """Run complete diagnosis and generate comprehensive report"""
        diagnosis = {
            "timestamp": "2024-04-04T19:30:00Z",
            "overall_status": "unknown",
            "services": {},
            "recommendations": [],
            "quick_fixes": []
        }
        
        # Diagnose each service
        slack_result = self.detect_and_fix_slack_issues()
        jira_result = self.detect_and_fix_jira_issues()
        notion_result = self.detect_and_fix_notion_issues()
        
        diagnosis["services"]["slack"] = slack_result
        diagnosis["services"]["jira"] = jira_result
        diagnosis["services"]["notion"] = notion_result
        
        # Determine overall status
        statuses = [s["status"] for s in diagnosis["services"].values()]
        if all(status == "healthy" for status in statuses):
            diagnosis["overall_status"] = "all_healthy"
        elif any(status == "healthy" for status in statuses):
            diagnosis["overall_status"] = "partial"
        else:
            diagnosis["overall_status"] = "needs_attention"
        
        # Generate specific quick fixes
        if slack_result["status"] == "needs_fixes":
            diagnosis["quick_fixes"].append("Slack: " + self.generate_slack_invitation_command(
                os.environ.get("SLACK_CHANNEL_ID", "YOUR_CHANNEL_ID")
            ))
            
        if jira_result["status"] == "needs_fixes":
            diagnosis["quick_fixes"].append("Jira: " + self.generate_jira_permission_fix_guide(
                os.environ.get("JIRA_PROJECT_KEY", "YOUR_PROJECT_KEY"),
                os.environ.get("JIRA_EMAIL", "your-email@domain.com")
            ))
            
        if notion_result["status"] == "needs_fixes":
            diagnosis["quick_fixes"].append("Notion: " + self.generate_notion_access_fix_guide(
                os.environ.get("NOTION_DATABASE_ID"),
                os.environ.get("NOTION_PARENT_PAGE_ID")
            ))
        
        # General recommendations
        diagnosis["recommendations"] = [
            "Test integrations after applying fixes",
            "Use OAuth for user-specific connections (recommended for production)",
            "Monitor integration health regularly",
            "Set up alerts for integration failures"
        ]
        
        return diagnosis
        
    def apply_automatic_fixes(self) -> Dict[str, Any]:
        """Apply automatic fixes where possible"""
        auto_fixes = {
            "applied": [],
            "manual": [],
            "success": False
        }
        
        # Auto-fix environment variable formatting issues
        env_file_path = ".env"
        
        try:
            with open(env_file_path, 'r') as f:
                content = f.read()
            
            fixes_needed = []
            
            # Fix BOM issues
            if content.startswith('\ufeff'):
                content = content[1:]
                fixes_needed.append("Removed BOM character")
                auto_fixes["applied"].append("Fixed BOM encoding issue")
            
            # Fix common formatting issues
            lines = content.split('\n')
            fixed_lines = []
            
            for line in lines:
                # Fix spacing around equals
                if '=' in line and not line.strip().startswith('#'):
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    fixed_lines.append(f"{key}={value}")
                else:
                    fixed_lines.append(line)
            
            if fixes_needed:
                with open(env_file_path, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(fixed_lines))
                auto_fixes["success"] = True
                
        except Exception as e:
            auto_fixes["manual"].append(f"Could not auto-fix .env file: {str(e)}")
        
        return auto_fixes

def run_integration_diagnosis_and_fix():
    """Main function to run diagnosis and apply fixes"""
    fixer = IntegrationAutoFixer()
    
    print("🔍 **Integration Diagnosis & Auto-Fix Tool**")
    print("=" * 50)
    
    # Run diagnosis
    diagnosis = fixer.run_complete_diagnosis()
    
    print(f"📊 Overall Status: {diagnosis['overall_status'].upper()}")
    print()
    
    # Print service status
    for service, result in diagnosis["services"].items():
        status_icon = "✅" if result["status"] == "healthy" else "⚠️" if result["status"] == "needs_fixes" else "❌"
        print(f"{status_icon} {service.upper()}: {result['status'].upper()}")
        
        if result["issues"]:
            print("   Issues found:")
            for issue in result["issues"]:
                print(f"   • {issue}")
                
        if result["fixes"]:
            print("   Recommended fixes:")
            for fix in result["fixes"]:
                print(f"   • {fix}")
        print()
    
    # Apply automatic fixes
    print("🔧 **Applying Automatic Fixes**")
    auto_fixes = fixer.apply_automatic_fixes()
    
    if auto_fixes["applied"]:
        print("✅ Automatic fixes applied:")
        for fix in auto_fixes["applied"]:
            print(f"   • {fix}")
    
    if auto_fixes["manual"]:
        print("⚠️ Manual fixes required:")
        for fix in auto_fixes["manual"]:
            print(f"   • {fix}")
    
    print()
    print("🚀 **Quick Fix Commands**")
    print("-" * 30)
    for quick_fix in diagnosis["quick_fixes"]:
        print(quick_fix)
        print()
    
    print("📋 **General Recommendations**")
    print("-" * 30)
    for rec in diagnosis["recommendations"]:
        print(f"• {rec}")
    
    return diagnosis

if __name__ == "__main__":
    run_integration_diagnosis_and_fix()
