"""
Integration Testing Dashboard
Web-based dashboard for testing and monitoring third-party integrations
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from dotenv import load_dotenv
load_dotenv('.env')

from enhanced_integrations import run_enhanced_integrations, get_integration_health_status
from integration_health_monitor import run_comprehensive_integration_test, get_integration_analytics
from integration_auto_fixer import run_integration_diagnosis_and_fix

app = FastAPI(title="Integration Dashboard", version="1.0.0")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
app.mount("/static", StaticFiles(directory="static"), name="static")

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Integration Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/axios/dist/axios.min.js"></script>
    <style>
        .status-healthy { color: #10b981; }
        .status-warning { color: #f59e0b; }
        .status-error { color: #ef4444; }
        .animate-pulse { animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite; }
    </style>
</head>
<body class="bg-gray-50 min-h-screen">
    <div class="container mx-auto p-6 max-w-6xl">
        <header class="mb-8">
            <h1 class="text-3xl font-bold text-gray-900 mb-2">🔗 Integration Dashboard</h1>
            <p class="text-gray-600">Monitor and test your third-party integrations</p>
        </header>

        <main class="space-y-8">
            <!-- Quick Actions -->
            <section class="bg-white rounded-lg shadow p-6">
                <h2 class="text-xl font-semibold mb-4">🚀 Quick Actions</h2>
                <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <button onclick="runDiagnosis()" class="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 transition">
                        🔍 Run Diagnosis
                    </button>
                    <button onclick="runComprehensiveTest()" class="bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700 transition">
                        🧪 Test All Integrations
                    </button>
                    <button onclick="runSampleMeeting()" class="bg-purple-600 text-white px-4 py-2 rounded hover:bg-purple-700 transition">
                        📋 Test Sample Meeting
                    </button>
                </div>
            </section>

            <!-- Integration Status -->
            <section class="bg-white rounded-lg shadow p-6">
                <h2 class="text-xl font-semibold mb-4">📊 Integration Status</h2>
                <div id="integration-status" class="space-y-4">
                    <div class="text-gray-500">Loading integration status...</div>
                </div>
            </section>

            <!-- Health Metrics -->
            <section class="bg-white rounded-lg shadow p-6">
                <h2 class="text-xl font-semibold mb-4">📈 Health Metrics</h2>
                <div id="health-metrics" class="space-y-4">
                    <div class="text-gray-500">Loading health metrics...</div>
                </div>
            </section>

            <!-- Test Results -->
            <section class="bg-white rounded-lg shadow p-6">
                <h2 class="text-xl font-semibold mb-4">🧪 Test Results</h2>
                <div id="test-results" class="space-y-4">
                    <div class="text-gray-500">No tests run yet</div>
                </div>
            </section>

            <!-- Environment Variables -->
            <section class="bg-white rounded-lg shadow p-6">
                <h2 class="text-xl font-semibold mb-4">⚙️ Configuration</h2>
                <div id="env-config" class="space-y-4">
                    <div class="text-gray-500">Loading configuration...</div>
                </div>
            </section>
        </main>

        <!-- Notifications -->
        <div id="notifications" class="fixed bottom-4 right-4 space-y-2 max-w-md"></div>
    </div>

    <script>
        let refreshInterval;

        async function showNotification(message, type = 'info') {
            const notification = document.createElement('div');
            notification.className = `p-4 rounded-lg shadow-lg transform transition-all duration-300 ${
                type === 'success' ? 'bg-green-500 text-white' :
                type === 'error' ? 'bg-red-500 text-white' :
                type === 'warning' ? 'bg-yellow-500 text-white' :
                'bg-blue-500 text-white'
            }`;
            notification.innerHTML = message;
            
            document.getElementById('notifications').appendChild(notification);
            
            setTimeout(() => {
                notification.style.opacity = '0';
                setTimeout(() => notification.remove(), 300);
            }, 5000);
        }

        async function loadIntegrationStatus() {
            try {
                const response = await axios.get('/api/health-status');
                const data = response.data;
                
                const statusHtml = Object.entries(data.providers || {}).map(([provider, status]) => `
                    <div class="border rounded-lg p-4">
                        <div class="flex items-center justify-between mb-2">
                            <h3 class="text-lg font-semibold">${provider.toUpperCase()}</h3>
                            <span class="px-2 py-1 rounded text-sm font-medium status-${status.status}">
                                ${status.status.toUpperCase()}
                            </span>
                        </div>
                        <div class="grid grid-cols-2 gap-4 text-sm">
                            <div>
                                <span class="font-medium">Uptime:</span>
                                <span class="${status.uptime_percentage >= 90 ? 'status-healthy' : status.uptime_percentage >= 70 ? 'status-warning' : 'status-error'}">
                                    ${status.uptime_percentage.toFixed(1)}%
                                </span>
                            </div>
                            <div>
                                <span class="font-medium">Success Rate:</span>
                                <span class="${status.success_rate >= 90 ? 'status-healthy' : status.success_rate >= 70 ? 'status-warning' : 'status-error'}">
                                    ${status.success_rate.toFixed(1)}%
                                </span>
                            </div>
                            <div>
                                <span class="font-medium">Avg Response:</span>
                                <span>${status.average_response_time.toFixed(2)}s</span>
                            </div>
                            <div>
                                <span class="font-medium">Total Calls:</span>
                                <span>${status.total_calls}</span>
                            </div>
                        </div>
                        ${status.last_error ? `<div class="mt-2 p-2 bg-red-50 rounded text-sm text-red-700">
                            <strong>Last Error:</strong> ${status.last_error}
                        </div>` : ''}
                    </div>
                `).join('');
                
                document.getElementById('integration-status').innerHTML = statusHtml || '<div class="text-gray-500">No integration data available</div>';
            } catch (error) {
                showNotification('Failed to load integration status', 'error');
            }
        }

        async function loadHealthMetrics() {
            try {
                const response = await axios.get('/api/analytics');
                const data = response.data;
                
                const metricsHtml = `
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div class="border rounded p-4">
                            <h4 class="font-semibold mb-2">Overall Health</h4>
                            <div class="text-2xl font-bold status-${data.health_summary?.overall_health === 'healthy' ? 'healthy' : data.health_summary?.overall_health === 'degraded' ? 'warning' : 'error'}">
                                ${data.health_summary?.overall_health?.toUpperCase() || 'UNKNOWN'}
                            </div>
                        </div>
                        <div class="border rounded p-4">
                            <h4 class="font-semibold mb-2">Active Integrations</h4>
                            <div class="text-2xl font-bold">
                                ${data.health_summary?.healthy_integrations || 0} / ${data.health_summary?.total_integrations || 0}
                            </div>
                        </div>
                    </div>
                `;
                
                document.getElementById('health-metrics').innerHTML = metricsHtml;
            } catch (error) {
                showNotification('Failed to load health metrics', 'error');
            }
        }

        async function loadEnvironmentConfig() {
            try {
                const response = await axios.get('/api/env-status');
                const data = response.data;
                
                const configHtml = `
                    <div class="space-y-4">
                        ${Object.entries(data.services || {}).map(([service, config]) => `
                            <div class="border rounded p-4">
                                <h4 class="font-semibold mb-2">${service.toUpperCase()}</h4>
                                <div class="space-y-2 text-sm">
                                    ${Object.entries(config).map(([key, value]) => `
                                        <div class="flex justify-between">
                                            <span class="font-medium">${key}:</span>
                                            <span class="${value ? 'status-healthy' : 'status-error'}">
                                                ${value ? '✅ Configured' : '❌ Missing'}
                                            </span>
                                        </div>
                                    `).join('')}
                                </div>
                            </div>
                        `).join('')}
                    </div>
                `;
                
                document.getElementById('env-config').innerHTML = configHtml;
            } catch (error) {
                showNotification('Failed to load configuration', 'error');
            }
        }

        async function runDiagnosis() {
            showNotification('Running integration diagnosis...', 'info');
            try {
                const response = await axios.post('/api/run-diagnosis');
                showNotification('Diagnosis completed! Check console output.', 'success');
                console.log('Diagnosis Results:', response.data);
            } catch (error) {
                showNotification('Failed to run diagnosis', 'error');
            }
        }

        async function runComprehensiveTest() {
            showNotification('Running comprehensive integration tests...', 'info');
            try {
                const response = await axios.post('/api/test-all');
                const data = response.data;
                
                const resultsHtml = `
                    <div class="space-y-4">
                        <div class="border rounded p-4">
                            <h4 class="font-semibold mb-2">Overall Status: ${data.overall_status}</h4>
                            <div class="text-sm text-gray-600">Tested at: ${data.timestamp}</div>
                        </div>
                        ${Object.entries(data.tests || {}).map(([provider, test]) => `
                            <div class="border rounded p-4">
                                <div class="flex items-center justify-between mb-2">
                                    <h4 class="font-semibold">${provider.toUpperCase()}</h4>
                                    <span class="px-2 py-1 rounded text-sm font-medium status-${test.status}">
                                        ${test.status.toUpperCase()}
                                    </span>
                                </div>
                                ${test.status === 'success' ? `
                                    <div class="text-sm space-y-1">
                                        <div><strong>Response Time:</strong> ${test.response_time?.toFixed(2)}s</div>
                                        ${test.channel_name ? `<div><strong>Channel:</strong> ${test.channel_name}</div>` : ''}
                                        ${test.project_name ? `<div><strong>Project:</strong> ${test.project_name}</div>` : ''}
                                        ${test.database_title ? `<div><strong>Database:</strong> ${test.database_title}</div>` : ''}
                                    </div>
                                ` : test.status === 'failed' || test.status === 'error' ? `
                                    <div class="mt-2 p-2 bg-red-50 rounded text-sm text-red-700">
                                        <strong>Error:</strong> ${test.error}
                                    </div>
                                ` : ''}
                            </div>
                        `).join('')}
                    </div>
                `;
                
                document.getElementById('test-results').innerHTML = resultsHtml;
                showNotification('Comprehensive test completed!', 'success');
            } catch (error) {
                showNotification('Failed to run comprehensive test', 'error');
            }
        }

        async function runSampleMeeting() {
            showNotification('Testing sample meeting integration...', 'info');
            try {
                const response = await axios.post('/api/test-meeting', {
                    title: 'Dashboard Test Meeting',
                    platform: 'zoom',
                    language: 'en',
                    summary: 'This is a test meeting from the integration dashboard to verify all services are working correctly.',
                    transcript: 'Sample transcript for testing purposes. This would contain the actual meeting content.',
                    participants: ['Alice', 'Bob', 'Charlie'],
                    output_filename: 'dashboard_test.txt'
                });
                
                const data = response.data;
                
                const resultHtml = `
                    <div class="space-y-4">
                        <div class="border rounded p-4">
                            <h4 class="font-semibold mb-2">Sample Meeting Test Results</h4>
                            <div class="text-sm space-y-2">
                                <div><strong>Execution Time:</strong> ${data.execution_time}s</div>
                                <div><strong>Slack:</strong> <span class="status-${data.slack === 'sent' ? 'healthy' : 'error'}">${data.slack}</span></div>
                                <div><strong>Jira:</strong> <span class="status-${data.jira?.startsWith('created') ? 'healthy' : 'error'}">${data.jira}</span></div>
                                <div><strong>Notion:</strong> <span class="status-${data.notion?.startsWith('created') ? 'healthy' : 'error'}">${data.notion}</span></div>
                                ${data.warnings?.length ? `
                                    <div class="mt-2 p-2 bg-yellow-50 rounded text-sm text-yellow-700">
                                        <strong>Warnings:</strong>
                                        <ul class="mt-1 ml-4">
                                            ${data.warnings.map(w => `<li>${w}</li>`).join('')}
                                        </ul>
                                    </div>
                                ` : ''}
                            </div>
                        </div>
                    </div>
                `;
                
                document.getElementById('test-results').innerHTML = resultHtml;
                showNotification('Sample meeting test completed!', 'success');
            } catch (error) {
                showNotification('Failed to run sample meeting test', 'error');
            }
        }

        // Auto-refresh every 30 seconds
        function startAutoRefresh() {
            loadIntegrationStatus();
            loadHealthMetrics();
            loadEnvironmentConfig();
            
            refreshInterval = setInterval(() => {
                loadIntegrationStatus();
                loadHealthMetrics();
            }, 30000);
        }

        // Initialize dashboard
        document.addEventListener('DOMContentLoaded', () => {
            startAutoRefresh();
            showNotification('Integration Dashboard loaded successfully!', 'success');
        });

        // Cleanup on page unload
        window.addEventListener('beforeunload', () => {
            if (refreshInterval) {
                clearInterval(refreshInterval);
            }
        });
    </script>
</body>
</html>
"""

@app.get("/")
async def dashboard_home():
    """Serve the integration dashboard"""
    return HTMLResponse(content=DASHBOARD_HTML)

@app.get("/api/health-status")
async def get_health_status():
    """Get integration health status"""
    try:
        return get_integration_health_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/analytics")
async def get_analytics():
    """Get integration analytics"""
    try:
        return get_integration_analytics(days=7)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/run-diagnosis")
async def run_diagnosis():
    """Run integration diagnosis"""
    try:
        result = run_integration_diagnosis_and_fix()
        return {"status": "completed", "diagnosis": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/test-all")
async def test_all_integrations():
    """Run comprehensive integration tests"""
    try:
        # Load environment variables
        slack_token = os.environ.get("SLACK_BOT_TOKEN") or os.environ.get("SLACK_TOKEN", "").strip()
        slack_channel_id = os.environ.get("SLACK_CHANNEL_ID", "").strip()
        
        jira_access_token = os.environ.get("JIRA_API_TOKEN", "").strip()
        jira_cloud_id = ""  # Not available in env mode
        jira_project_key = os.environ.get("JIRA_PROJECT_KEY", "").strip()
        
        notion_token = os.environ.get("NOTION_TOKEN") or os.environ.get("NOTION_API_TOKEN", "").strip()
        notion_database_id = os.environ.get("NOTION_DATABASE_ID", "").strip()
        notion_parent_page_id = os.environ.get("NOTION_PARENT_PAGE_ID", "").strip()
        
        result = await run_comprehensive_integration_test(
            slack_token=slack_token,
            slack_channel_id=slack_channel_id,
            jira_access_token=jira_access_token,
            jira_cloud_id=jira_cloud_id,
            jira_project_key=jira_project_key,
            notion_token=notion_token,
            notion_database_id=notion_database_id,
            notion_parent_page_id=notion_parent_page_id
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/test-meeting")
async def test_meeting_integration(request):
    """Test with sample meeting data"""
    try:
        data = await request.json()
        result = run_enhanced_integrations(**data)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/env-status")
async def get_env_status():
    """Get environment variable status"""
    services = {}
    
    # Check Slack
    slack_config = {}
    slack_token = os.environ.get("SLACK_BOT_TOKEN") or os.environ.get("SLACK_TOKEN", "").strip()
    slack_channel_id = os.environ.get("SLACK_CHANNEL_ID", "").strip()
    slack_webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    
    slack_config["token"] = bool(slack_token)
    slack_config["channel_id"] = bool(slack_channel_id)
    slack_config["webhook"] = bool(slack_webhook)
    services["slack"] = slack_config
    
    # Check Jira
    jira_config = {}
    jira_url = os.environ.get("JIRA_BASE_URL", "").strip()
    jira_email = os.environ.get("JIRA_EMAIL", "").strip()
    jira_token = os.environ.get("JIRA_API_TOKEN", "").strip()
    jira_project_key = os.environ.get("JIRA_PROJECT_KEY", "").strip()
    
    jira_config["url"] = bool(jira_url)
    jira_config["email"] = bool(jira_email)
    jira_config["token"] = bool(jira_token)
    jira_config["project_key"] = bool(jira_project_key)
    services["jira"] = jira_config
    
    # Check Notion
    notion_config = {}
    notion_token = os.environ.get("NOTION_TOKEN") or os.environ.get("NOTION_API_TOKEN", "").strip()
    notion_database_id = os.environ.get("NOTION_DATABASE_ID", "").strip()
    notion_parent_page_id = os.environ.get("NOTION_PARENT_PAGE_ID", "").strip()
    
    notion_config["token"] = bool(notion_token)
    notion_config["database_id"] = bool(notion_database_id)
    notion_config["parent_page_id"] = bool(notion_parent_page_id)
    services["notion"] = notion_config
    
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": services
    }

if __name__ == "__main__":
    import uvicorn
    
    print("🚀 Starting Integration Dashboard on http://localhost:8001")
    print("📊 Access the dashboard at: http://localhost:8001")
    print("🔍 API endpoints available at: http://localhost:8001/api")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8001,
        log_level="info"
    )
