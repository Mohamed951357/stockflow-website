"""
Test script for new user status and typing indicator endpoints
"""
import requests
import json
from datetime import datetime, timedelta

# Configuration
BASE_URL = "https://www.stock-flow.site/api/mobile"
TEST_USER_ID = 1  # Replace with actual user ID for testing

# Test data
test_credentials = {
    "username": "test_company",  # Replace with actual username
    "password": "test_password"   # Replace with actual password
}

def test_endpoints():
    """Test all new endpoints"""
    session = requests.Session()
    
    print("=" * 60)
    print("Testing User Status and Typing Indicator Endpoints")
    print("=" * 60)
    
    # 1. Login first
    print("\n1. Logging in...")
    login_response = session.post(
        f"{BASE_URL}/login",
        json=test_credentials
    )
    
    if login_response.status_code != 200:
        print(f"✗ Login failed: {login_response.status_code}")
        print(f"Response: {login_response.text}")
        return
    
    print("✓ Login successful")
    login_data = login_response.json()
    if login_data.get('success'):
        print(f"  User ID: {login_data.get('user_id')}")
    
    # 2. Test get user status endpoint
    print("\n2. Testing GET /users/<user_id>/status...")
    status_response = session.get(
        f"{BASE_URL}/users/{TEST_USER_ID}/status"
    )
    
    if status_response.status_code == 200:
        print("✓ Status endpoint works")
        status_data = status_response.json()
        print(f"  Response: {json.dumps(status_data, indent=2)}")
        print(f"  - is_online: {status_data.get('is_online')}")
        print(f"  - last_seen: {status_data.get('last_seen')}")
    else:
        print(f"✗ Status endpoint failed: {status_response.status_code}")
        print(f"Response: {status_response.text}")
    
    # 3. Test send typing status endpoint
    print("\n3. Testing POST /messages/typing (send typing status)...")
    typing_send_response = session.post(
        f"{BASE_URL}/messages/typing",
        json={"is_typing": True}
    )
    
    if typing_send_response.status_code == 200:
        print("✓ Send typing status endpoint works")
        typing_data = typing_send_response.json()
        print(f"  Response: {json.dumps(typing_data, indent=2)}")
    else:
        print(f"✗ Send typing status endpoint failed: {typing_send_response.status_code}")
        print(f"Response: {typing_send_response.text}")
    
    # 4. Test get typing status endpoint
    print("\n4. Testing GET /messages/typing/<user_id>...")
    typing_get_response = session.get(
        f"{BASE_URL}/messages/typing/{TEST_USER_ID}"
    )
    
    if typing_get_response.status_code == 200:
        print("✓ Get typing status endpoint works")
        typing_data = typing_get_response.json()
        print(f"  Response: {json.dumps(typing_data, indent=2)}")
        print(f"  - is_typing: {typing_data.get('is_typing')}")
    else:
        print(f"✗ Get typing status endpoint failed: {typing_get_response.status_code}")
        print(f"Response: {typing_get_response.text}")
    
    # 5. Test sending typing false
    print("\n5. Testing POST /messages/typing (stop typing)...")
    typing_stop_response = session.post(
        f"{BASE_URL}/messages/typing",
        json={"is_typing": False}
    )
    
    if typing_stop_response.status_code == 200:
        print("✓ Stop typing status endpoint works")
        typing_data = typing_stop_response.json()
        print(f"  Response: {json.dumps(typing_data, indent=2)}")
    else:
        print(f"✗ Stop typing status endpoint failed: {typing_stop_response.status_code}")
        print(f"Response: {typing_stop_response.text}")
    
    print("\n" + "=" * 60)
    print("Testing completed!")
    print("=" * 60)

if __name__ == "__main__":
    print("\nNote: Update test_credentials and TEST_USER_ID before running this test!\n")
    test_endpoints()
