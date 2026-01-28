"""Debug script with correct Accept header."""

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

# FIXED: Add Accept header
headers = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream"
}

print("=" * 60)
print("DEBUG: Producer Pal Response (with correct headers)")
print("=" * 60)

print("\n[1] Sending request to:", url)
print("Headers:", json.dumps(headers, indent=2))
print("Payload:", json.dumps(payload, indent=2))

try:
    response = requests.post(
        url,
        json=payload,
        headers=headers,
        timeout=30
    )
    
    print("\n[2] Response received:")
    print(f"  Status Code: {response.status_code}")
    print(f"  Content-Type: {response.headers.get('Content-Type')}")
    
    print("\n[3] Raw response (first 500 chars):")
    print("-" * 60)
    print(response.text[:500])
    print("-" * 60)
    
    if response.status_code == 200:
        print("\n[4] Parsed JSON:")
        data = response.json()
        
        if "error" in data:
            print(f"✗ JSON-RPC Error: {data['error']}")
        elif "result" in data:
            print("✓ Success!")
            result = data['result']
            print(f"  Tempo: {result.get('tempo', 'N/A')}")
            print(f"  Tracks count: {len(result.get('tracks', []))}")
        else:
            print("Unexpected response format:")
            print(json.dumps(data, indent=2))
    else:
        print(f"\n✗ HTTP Error {response.status_code}")
        print(response.text)
        
except requests.ConnectionError as e:
    print(f"\n✗ Connection failed: {e}")
    print("\nMake sure:")
    print("  1. Ableton Live is running")
    print("  2. Producer Pal device is loaded")
    print("  3. Producer Pal shows 'Server running on port 3350'")
except Exception as e:
    print(f"\n✗ Unexpected error: {e}")
    import traceback
    traceback.print_exc()
