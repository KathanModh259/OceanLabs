#!/usr/bin/env python3
"""
Integration test script for Slack, Jira, and Notion OAuth integrations.
Run this script to verify that your third-party integrations are working properly.
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv('.env')

# Add the current directory to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from integrations import run_post_meeting_integrations
    from integration_store import list_user_integrations, get_user_integration
    from oauth_integrations import build_oauth_authorize_url, handle_oauth_callback
    INTEGRATIONS_AVAILABLE = True
except ImportError as e:
    print(f"❌ Integration modules not available: {e}")
    INTEGRATIONS_AVAILABLE = False


def check_environment_variables():
    """Check if required environment variables are set."""
    print("🔍 Checking environment variables...")
    
    required_vars = {
        'SLACK_OAUTH_CLIENT_ID': 'Slack',
        'SLACK_OAUTH_CLIENT_SECRET': 'Slack',
        'JIRA_OAUTH_CLIENT_ID': 'Jira', 
        'JIRA_OAUTH_CLIENT_SECRET': 'Jira',
        'NOTION_OAUTH_CLIENT_ID': 'Notion',
        'NOTION_OAUTH_CLIENT_SECRET': 'Notion',
        'SUPABASE_URL': 'Supabase',
        'SUPABASE_SERVICE_ROLE_KEY': 'Supabase',
    }
    
    missing_vars = []
    present_vars = []
    
    for var, service in required_vars.items():
        value = os.environ.get(var)
        if value and value.strip():
            present_vars.append(f"✅ {service}: {var}")
        else:
            missing_vars.append(f"❌ {service}: {var}")
    
    print("\n📋 Environment Variable Status:")
    for status in present_vars + missing_vars:
        print(f"  {status}")
    
    return len(missing_vars) == 0


def check_integration_modules():
    """Check if integration modules are properly imported."""
    print("\n🔍 Checking integration modules...")
    
    if INTEGRATIONS_AVAILABLE:
        print("✅ All integration modules imported successfully")
        return True
    else:
        print("❌ Integration modules failed to import")
        return False


def test_oauth_url_generation():
    """Test OAuth authorization URL generation."""
    print("\n🔍 Testing OAuth URL generation...")
    
    if not INTEGRATIONS_AVAILABLE:
        print("❌ Cannot test OAuth - modules not available")
        return False
    
    test_user_id = "test-user-123"
    providers = ["slack", "jira", "notion"]
    results = {}
    
    for provider in providers:
        try:
            success, payload = build_oauth_authorize_url(provider, test_user_id, None)
            if success:
                results[provider] = "✅ Success"
                print(f"  ✅ {provider.capitalize()}: OAuth URL generated successfully")
            else:
                results[provider] = f"❌ Error: {payload.get('error', 'Unknown error')}"
                print(f"  ❌ {provider.capitalize()}: {payload.get('error', 'Unknown error')}")
        except Exception as e:
            results[provider] = f"❌ Exception: {str(e)}"
            print(f"  ❌ {provider.capitalize()}: Exception - {str(e)}")
    
    return all("✅" in result for result in results.values())


def test_integration_dispatch():
    """Test the integration dispatch functionality."""
    print("\n🔍 Testing integration dispatch...")
    
    if not INTEGRATIONS_AVAILABLE:
        print("❌ Cannot test dispatch - modules not available")
        return False
    
    # Test data for a mock meeting
    test_data = {
        "title": "Test Integration Meeting",
        "platform": "zoom",
        "language": "en",
        "summary": "This is a test meeting summary to verify integrations are working.",
        "transcript": "This is the full transcript of the test meeting.",
        "participants": ["Alice", "Bob", "Charlie"],
        "output_filename": "test_meeting.txt",
        "requester_user_id": None  # Test with environment variables
    }
    
    try:
        result = run_post_meeting_integrations(**test_data)
        print("  📊 Integration Results:")
        print(f"    Slack: {result.get('slack', 'unknown')}")
        print(f"    Jira: {result.get('jira', 'unknown')}")
        print(f"    Notion: {result.get('notion', 'unknown')}")
        
        if result.get('warnings'):
            print("  ⚠️  Warnings:")
            for warning in result.get('warnings', []):
                print(f"    - {warning}")
        
        return True
    except Exception as e:
        print(f"  ❌ Integration dispatch failed: {str(e)}")
        return False


def test_database_connection():
    """Test Supabase database connection."""
    print("\n🔍 Testing database connection...")
    
    if not INTEGRATIONS_AVAILABLE:
        print("❌ Cannot test database - modules not available")
        return False
    
    try:
        # Try to list integrations for a test user (should return empty if no data)
        test_user_id = "test-nonexistent-user"
        integrations = list_user_integrations(test_user_id)
        print(f"  ✅ Database connection successful (returned {len(integrations)} integrations)")
        return True
    except Exception as e:
        print(f"  ❌ Database connection failed: {str(e)}")
        return False


def main():
    """Run all integration tests."""
    print("🚀 Starting Third-Party Integration Tests")
    print("=" * 50)
    print(f"📅 Test started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Run all tests
    tests = [
        ("Environment Variables", check_environment_variables),
        ("Integration Modules", check_integration_modules),
        ("Database Connection", test_database_connection),
        ("OAuth URL Generation", test_oauth_url_generation),
        ("Integration Dispatch", test_integration_dispatch),
    ]
    
    results = {}
    for test_name, test_func in tests:
        try:
            results[test_name] = test_func()
        except Exception as e:
            print(f"❌ {test_name} failed with exception: {str(e)}")
            results[test_name] = False
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 TEST SUMMARY")
    print("=" * 50)
    
    passed = sum(1 for result in results.values() if result)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {test_name:<25} {status}")
    
    print(f"\n🎯 Overall Result: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Your integrations are ready to use.")
        return 0
    else:
        print("⚠️  Some tests failed. Check the configuration and try again.")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
