"""
Integration Health Monitoring and Analytics System
Provides comprehensive monitoring, logging, and analytics for third-party integrations
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from pathlib import Path

import httpx
from integration_store import list_user_integrations

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/integration_health.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class IntegrationMetrics:
    """Metrics for integration performance tracking"""
    provider: str
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    average_response_time: float = 0.0
    last_success: Optional[str] = None
    last_failure: Optional[str] = None
    last_error_message: Optional[str] = None
    uptime_percentage: float = 100.0
    consecutive_failures: int = 0

class IntegrationHealthMonitor:
    """Advanced health monitoring with analytics and alerting"""
    
    def __init__(self, log_file: str = "logs/integration_metrics.json"):
        self.metrics: Dict[str, IntegrationMetrics] = {}
        self.log_file = Path(log_file)
        self.alert_threshold = 3  # Alert after 3 consecutive failures
        self.metrics_history: List[Dict] = []
        self.load_metrics()
        
    def load_metrics(self):
        """Load historical metrics from file"""
        try:
            if self.log_file.exists():
                with open(self.log_file, 'r') as f:
                    data = json.load(f)
                    for provider, metrics_data in data.items():
                        self.metrics[provider] = IntegrationMetrics(**metrics_data)
        except Exception as e:
            logger.warning(f"Failed to load metrics: {e}")
            
    def save_metrics(self):
        """Save metrics to file"""
        try:
            self.log_file.parent.mkdir(exist_ok=True)
            with open(self.log_file, 'w') as f:
                json.dump({k: asdict(v) for k, v in self.metrics.items()}, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save metrics: {e}")
            
    def record_success(self, provider: str, response_time: float = 0.0, details: str = ""):
        """Record successful integration call"""
        if provider not in self.metrics:
            self.metrics[provider] = IntegrationMetrics(provider=provider)
            
        metrics = self.metrics[provider]
        metrics.total_calls += 1
        metrics.successful_calls += 1
        metrics.consecutive_failures = 0
        metrics.last_success = datetime.now(timezone.utc).isoformat()
        metrics.last_error_message = None
        
        # Update average response time
        if response_time > 0:
            metrics.average_response_time = (
                (metrics.average_response_time * (metrics.successful_calls - 1) + response_time) 
                / metrics.successful_calls
            )
        
        # Calculate uptime percentage
        metrics.uptime_percentage = (metrics.successful_calls / metrics.total_calls) * 100
        
        logger.info(f"✅ {provider}: Success (Response: {response_time:.2f}s, Uptime: {metrics.uptime_percentage:.1f}%)")
        self.save_metrics()
        
    def record_failure(self, provider: str, error_message: str, response_time: float = 0.0):
        """Record failed integration call"""
        if provider not in self.metrics:
            self.metrics[provider] = IntegrationMetrics(provider=provider)
            
        metrics = self.metrics[provider]
        metrics.total_calls += 1
        metrics.failed_calls += 1
        metrics.consecutive_failures += 1
        metrics.last_failure = datetime.now(timezone.utc).isoformat()
        metrics.last_error_message = error_message
        
        # Calculate uptime percentage
        metrics.uptime_percentage = (metrics.successful_calls / metrics.total_calls) * 100
        
        logger.error(f"❌ {provider}: {error_message} (Consecutive failures: {metrics.consecutive_failures})")
        
        # Check for alert threshold
        if metrics.consecutive_failures >= self.alert_threshold:
            self.send_alert(provider, metrics)
            
        self.save_metrics()
        
    def send_alert(self, provider: str, metrics: IntegrationMetrics):
        """Send alert for consecutive failures"""
        alert_message = f"""
🚨 INTEGRATION ALERT 🚨

Provider: {provider.upper()}
Consecutive Failures: {metrics.consecutive_failures}
Uptime: {metrics.uptime_percentage:.1f}%
Last Error: {metrics.last_error_message}
Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}

Recommendation: Check integration configuration and permissions.
        """
        
        logger.critical(alert_message)
        
        # Here you could add email, Slack, or other alerting mechanisms
        # For now, just log it
        
    def get_health_summary(self) -> Dict[str, Any]:
        """Get comprehensive health summary"""
        summary = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "providers": {},
            "overall_health": "healthy",
            "total_integrations": len(self.metrics),
            "healthy_integrations": 0,
            "unhealthy_integrations": 0
        }
        
        for provider, metrics in self.metrics.items():
            is_healthy = metrics.consecutive_failures < self.alert_threshold and metrics.uptime_percentage >= 80
            
            summary["providers"][provider] = {
                "status": "healthy" if is_healthy else "unhealthy",
                "uptime_percentage": metrics.uptime_percentage,
                "total_calls": metrics.total_calls,
                "success_rate": (metrics.successful_calls / metrics.total_calls * 100) if metrics.total_calls > 0 else 0,
                "average_response_time": metrics.average_response_time,
                "last_success": metrics.last_success,
                "last_failure": metrics.last_failure,
                "consecutive_failures": metrics.consecutive_failures,
                "last_error": metrics.last_error_message
            }
            
            if is_healthy:
                summary["healthy_integrations"] += 1
            else:
                summary["unhealthy_integrations"] += 1
                
        # Determine overall health
        if summary["unhealthy_integrations"] > 0:
            summary["overall_health"] = "degraded"
        if summary["unhealthy_integrations"] == summary["total_integrations"] and summary["total_integrations"] > 0:
            summary["overall_health"] = "unhealthy"
            
        return summary
        
    def get_provider_recommendations(self, provider: str) -> List[str]:
        """Get specific recommendations for a provider"""
        if provider not in self.metrics:
            return ["No data available for this provider"]
            
        metrics = self.metrics[provider]
        recommendations = []
        
        if metrics.uptime_percentage < 90:
            recommendations.append(f"Low uptime ({metrics.uptime_percentage:.1f}%). Check integration stability.")
            
        if metrics.consecutive_failures >= 2:
            recommendations.append(f"Multiple consecutive failures ({metrics.consecutive_failures}). Verify configuration.")
            
        if metrics.average_response_time > 10.0:
            recommendations.append(f"Slow response time ({metrics.average_response_time:.2f}s). Check API performance.")
            
        if "not_in_channel" in str(metrics.last_error_message or ""):
            recommendations.append("Bot not in Slack channel. Use /invite @bot-name to add.")
            
        if "permission" in str(metrics.last_error_message or "").lower():
            recommendations.append("Permission denied. Check user permissions and project access.")
            
        if "invalid_auth" in str(metrics.last_error_message or "").lower():
            recommendations.append("Authentication failed. Check API tokens and OAuth setup.")
            
        return recommendations
        
    def reset_metrics(self, provider: str = None):
        """Reset metrics for specific provider or all"""
        if provider:
            self.metrics.pop(provider, None)
            logger.info(f"Reset metrics for {provider}")
        else:
            self.metrics.clear()
            logger.info("Reset all metrics")

class IntegrationTester:
    """Automated integration testing with comprehensive validation"""
    
    def __init__(self, health_monitor: IntegrationHealthMonitor):
        self.health_monitor = health_monitor
        
    async def test_slack_integration(self, token: str, channel_id: str) -> Dict[str, Any]:
        """Test Slack integration with comprehensive validation"""
        start_time = asyncio.get_event_loop().time()
        
        try:
            # Test bot info
            async with httpx.AsyncClient(timeout=10.0) as client:
                auth_response = await client.get(
                    "https://slack.com/api/auth.test",
                    headers={"Authorization": f"Bearer {token}"}
                )
                
            if auth_response.status_code != 200:
                return {
                    "status": "failed",
                    "error": "Invalid bot token",
                    "details": auth_response.text
                }
                
            # Test channel access
            async with httpx.AsyncClient(timeout=10.0) as client:
                channel_response = await client.get(
                    f"https://slack.com/api/conversations.info",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"channel": channel_id}
                )
                
            response_time = asyncio.get_event_loop().time() - start_time
            
            if channel_response.status_code == 200:
                channel_data = channel_response.json()
                if channel_data.get("ok"):
                    self.health_monitor.record_success("slack", response_time)
                    return {
                        "status": "success",
                        "response_time": response_time,
                        "channel_name": channel_data.get("channel", {}).get("name"),
                        "is_member": True
                    }
                else:
                    self.health_monitor.record_failure("slack", f"Channel access error: {channel_data.get('error')}")
                    return {
                        "status": "failed",
                        "error": "Cannot access channel",
                        "details": channel_data.get("error")
                    }
            else:
                self.health_monitor.record_failure("slack", f"HTTP {channel_response.status_code}")
                return {
                    "status": "failed",
                    "error": f"HTTP {channel_response.status_code}",
                    "details": channel_response.text
                }
                
        except Exception as e:
            self.health_monitor.record_failure("slack", str(e))
            return {
                "status": "error",
                "error": str(e)
            }
            
    async def test_jira_integration(self, access_token: str, cloud_id: str, project_key: str) -> Dict[str, Any]:
        """Test Jira integration with comprehensive validation"""
        start_time = asyncio.get_event_loop().time()
        
        try:
            # Test user permissions
            async with httpx.AsyncClient(timeout=15.0) as client:
                permissions_response = await client.get(
                    f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/mypermissions",
                    headers={"Authorization": f"Bearer {access_token}"}
                )
                
            response_time = asyncio.get_event_loop().time() - start_time
            
            if permissions_response.status_code == 200:
                permissions = permissions_response.json()
                
                # Check project access
                async with httpx.AsyncClient(timeout=15.0) as client:
                    project_response = await client.get(
                        f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/project/{project_key}",
                        headers={"Authorization": f"Bearer {access_token}"}
                    )
                    
                if project_response.status_code == 200:
                    project_data = project_response.json()
                    self.health_monitor.record_success("jira", response_time)
                    return {
                        "status": "success",
                        "response_time": response_time,
                        "project_name": project_data.get("name"),
                        "project_key": project_key,
                        "can_create_issues": permissions.get("permissions", {}).get("BROWSE", {}).get("projects", {}).get(project_key, {}).get("issues", {}).get("CREATE", False)
                    }
                else:
                    self.health_monitor.record_failure("jira", f"Project access denied: {project_key}")
                    return {
                        "status": "failed",
                        "error": "Cannot access project",
                        "details": f"Project {project_key} not accessible"
                    }
            else:
                self.health_monitor.record_failure("jira", f"HTTP {permissions_response.status_code}")
                return {
                    "status": "failed",
                    "error": f"HTTP {permissions_response.status_code}",
                    "details": permissions_response.text
                }
                
        except Exception as e:
            self.health_monitor.record_failure("jira", str(e))
            return {
                "status": "error",
                "error": str(e)
            }
            
    async def test_notion_integration(self, token: str, database_id: str = None, parent_page_id: str = None) -> Dict[str, Any]:
        """Test Notion integration with comprehensive validation"""
        start_time = asyncio.get_event_loop().time()
        
        try:
            # Test bot permissions
            async with httpx.AsyncClient(timeout=15.0) as client:
                test_headers = {
                    "Authorization": f"Bearer {token}",
                    "Notion-Version": "2022-06-28"
                }
                
                # Test database access if provided
                if database_id:
                    db_response = await client.get(
                        f"https://api.notion.com/v1/databases/{database_id}",
                        headers=test_headers
                    )
                    
                    response_time = asyncio.get_event_loop().time() - start_time
                    
                    if db_response.status_code == 200:
                        db_data = db_response.json()
                        self.health_monitor.record_success("notion", response_time)
                        return {
                            "status": "success",
                            "response_time": response_time,
                            "database_title": db_data.get("title", [{}])[0].get("title", "Untitled"),
                            "database_id": database_id,
                            "can_create_pages": True
                        }
                    else:
                        self.health_monitor.record_failure("notion", f"Database access error: {database_id}")
                        return {
                            "status": "failed",
                            "error": "Cannot access database",
                            "details": db_response.text
                        }
                        
                # Test parent page access if provided
                elif parent_page_id:
                    page_response = await client.get(
                        f"https://api.notion.com/v1/pages/{parent_page_id}",
                        headers=test_headers
                    )
                    
                    response_time = asyncio.get_event_loop().time() - start_time
                    
                    if page_response.status_code == 200:
                        page_data = page_response.json()
                        self.health_monitor.record_success("notion", response_time)
                        return {
                            "status": "success",
                            "response_time": response_time,
                            "page_title": page_data.get("properties", {}).get("Name", [{}])[0].get("title", "Untitled"),
                            "page_id": parent_page_id,
                            "can_create_pages": True
                        }
                    else:
                        self.health_monitor.record_failure("notion", f"Page access error: {parent_page_id}")
                        return {
                            "status": "failed",
                            "error": "Cannot access parent page",
                            "details": page_response.text
                        }
                else:
                    self.health_monitor.record_failure("notion", "No database_id or parent_page_id provided")
                    return {
                        "status": "failed",
                        "error": "Missing target",
                        "details": "Either database_id or parent_page_id must be provided"
                    }
                    
        except Exception as e:
            self.health_monitor.record_failure("notion", str(e))
            return {
                "status": "error",
                "error": str(e)
            }

# Global health monitor instance
health_monitor = IntegrationHealthMonitor()
integration_tester = IntegrationTester(health_monitor)

async def run_comprehensive_integration_test(
    slack_token: str = None,
    slack_channel_id: str = None,
    jira_access_token: str = None,
    jira_cloud_id: str = None,
    jira_project_key: str = None,
    notion_token: str = None,
    notion_database_id: str = None,
    notion_parent_page_id: str = None
) -> Dict[str, Any]:
    """Run comprehensive tests for all configured integrations"""
    
    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tests": {},
        "overall_status": "unknown",
        "recommendations": []
    }
    
    test_count = 0
    
    # Test Slack
    if slack_token and slack_channel_id:
        test_count += 1
        results["tests"]["slack"] = await integration_tester.test_slack_integration(slack_token, slack_channel_id)
        
    # Test Jira
    if jira_access_token and jira_cloud_id and jira_project_key:
        test_count += 1
        results["tests"]["jira"] = await integration_tester.test_jira_integration(
            jira_access_token, jira_cloud_id, jira_project_key
        )
        
    # Test Notion
    if notion_token and (notion_database_id or notion_parent_page_id):
        test_count += 1
        results["tests"]["notion"] = await integration_tester.test_notion_integration(
            notion_token, notion_database_id, notion_parent_page_id
        )
    
    # Determine overall status
    successful_tests = sum(1 for test in results["tests"].values() if test.get("status") == "success")
    
    if test_count == 0:
        results["overall_status"] = "no_configurations"
    elif successful_tests == test_count:
        results["overall_status"] = "all_healthy"
    elif successful_tests > 0:
        results["overall_status"] = "partial"
    else:
        results["overall_status"] = "all_failed"
    
    # Generate recommendations
    for provider, test_result in results["tests"].items():
        if test_result.get("status") in ["failed", "error"]:
            recommendations = health_monitor.get_provider_recommendations(provider)
            results["recommendations"].extend(recommendations)
    
    return results

def get_integration_analytics(days: int = 7) -> Dict[str, Any]:
    """Get integration analytics for the specified time period"""
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
    
    return {
        "period_days": days,
        "cutoff_date": cutoff_date.isoformat(),
        "health_summary": health_monitor.get_health_summary(),
        "metrics": {k: asdict(v) for k, v in health_monitor.metrics.items()},
        "recommendations": {
            provider: health_monitor.get_provider_recommendations(provider)
            for provider in health_monitor.metrics.keys()
        }
    }
