"""Debug script to see what Producer Pal returns."""

import requests
import json

url = "http://localhost:3350/mcp"

payload = {
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
        "name": "ppal-read-live-set",
        "arguments": {}
    },
    "id": 1
}

print("=" * 60)
print("DEBUG: Producer Pal Response")
print("=" * 60)

print("\n[1] Sending request to:", url)
print("Payload:", json.dumps(payload, indent=2))

try:
    response = requests.post(
        url,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=30
    )
    
    print("\n[2] Response received:")
    print(f"  Status Code: {response.status_code}")
    print(f"  Content-Type: {response.headers.get('Content-Type')}")
    print(f"  Content-Length: {response.headers.get('Content-Length')}")
    
    print("\n[3] Raw response text:")
    print("-" * 60)
    print(response.text)
    print("-" * 60)
    
    print("\n[4] Attempting JSON parse...")
    if response.text:
        data = response.json()
        print("✓ Valid JSON:")
        print(json.dumps(data, indent=2))
    else:
        print("✗ Empty response body!")
        
except requests.ConnectionError as e:
    print(f"\n✗ Connection failed: {e}")
    print("\nMake sure:")
    print("  1. Ableton Live is running")
    print("  2. Producer Pal device is loaded")
    print("  3. Producer Pal shows 'Server running on port 3350'")
except requests.HTTPError as e:
    print(f"\n✗ HTTP error: {e}")
    print(f"Response: {response.text}")
except Exception as e:
    print(f"\n✗ Unexpected error: {e}")
    import traceback
    traceback.print_exc()
