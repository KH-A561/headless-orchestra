"""Test Producer Pal with initialize handshake first."""

import requests
import json

url = "http://localhost:3350/mcp"

print("=" * 60)
print("TEST: Producer Pal with initialize handshake")
print("=" * 60)

# Step 1: Initialize
print("\n[1] Sending initialize...")
init_payload = {
    "jsonrpc": "2.0",
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {
            "name": "headless-orchestra",
            "version": "0.1.0"
        }
    },
    "id": 1
}

try:
    response = requests.post(url, json=init_payload, timeout=10)
    print(f"  Status: {response.status_code}")
    print(f"  Response: {response.text[:200]}")
    
    if response.status_code == 200 and response.text:
        init_result = response.json()
        print("  ✓ Initialize successful")
        print(f"  Server info: {init_result.get('result', {})}")
    else:
        print("  ✗ Initialize failed or empty")
        
except Exception as e:
    print(f"  ✗ Error: {e}")
    import traceback
    traceback.print_exc()

# Step 2: Call tool
print("\n[2] Sending tools/call (ppal-read-live-set)...")
tool_payload = {
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
        "name": "ppal-read-live-set",
        "arguments": {}
    },
    "id": 2
}

try:
    response = requests.post(url, json=tool_payload, timeout=10)
    print(f"  Status: {response.status_code}")
    print(f"  Response length: {len(response.text)} chars")
    
    if response.text:
        result = response.json()
        print("  ✓ Tool call successful")
        print(f"  Result: {json.dumps(result, indent=2)[:500]}")
    else:
        print("  ✗ Empty response")
        
except Exception as e:
    print(f"  ✗ Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
