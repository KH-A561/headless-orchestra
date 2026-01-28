"""Test full parsing pipeline: SSE → MCP → JS object."""

import requests
import json
import re

url = "http://localhost:3350/mcp"
payload = {
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {"name": "ppal-read-live-set", "arguments": {}},
    "id": 1
}
headers = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream"
}

def parse_sse(sse_text):
    """Layer 1: Parse SSE."""
    lines = sse_text.strip().split('\n')
    for line in lines:
        if line.startswith('data: '):
            return json.loads(line[6:])
    raise ValueError("No data in SSE")

def parse_js_object(js_text):
    """Layer 3: Parse JavaScript object notation."""
    # Add quotes to unquoted keys
    json_text = re.sub(r'(\w+):', r'"\1":', js_text)
    return json.loads(json_text)

print("=" * 60)
print("FULL PIPELINE TEST")
print("=" * 60)

try:
    response = requests.post(url, json=payload, headers=headers, timeout=30)
    response.raise_for_status()
    
    # Layer 1: SSE
    print("\n[Layer 1] Parsing SSE...")
    json_rpc = parse_sse(response.text)
    print(f"  ✓ JSON-RPC keys: {list(json_rpc.keys())}")
    
    # Layer 2: MCP content
    print("\n[Layer 2] Extracting MCP content...")
    result = json_rpc.get("result", {})
    content = result.get("content", [])
    print(f"  ✓ Content blocks: {len(content)}")
    
    if content:
        first_block = content[0]
        print(f"  ✓ First block type: {first_block.get('type')}")
        
        if first_block.get("type") == "text":
            js_text = first_block.get("text", "")
            print(f"  ✓ JS text length: {len(js_text)} chars")
            print(f"  ✓ JS text (first 200 chars):\n    {js_text[:200]}")
            
            # Layer 3: JS object
            print("\n[Layer 3] Parsing JavaScript object...")
            final_data = parse_js_object(js_text)
            print(f"  ✓ Parsed successfully!")
            print(f"  ✓ Keys: {list(final_data.keys())}")
            print(f"\n[Final Result]")
            print(f"  ID: {final_data.get('id')}")
            print(f"  Tempo: {final_data.get('tempo')}")
            print(f"  Time Signature: {final_data.get('timeSignature')}")
            print(f"  Tracks: {len(final_data.get('tracks', []))}")
            
            # Show first track
            tracks = final_data.get('tracks', [])
            if tracks:
                print(f"\n[First Track]")
                track = tracks[0]
                print(f"  ID: {track.get('id')}")
                print(f"  Name: {track.get('name')}")
                print(f"  Type: {track.get('type')}")
                print(f"  Index: {track.get('trackIndex')}")
    
    print("\n" + "=" * 60)
    print("✓ ALL LAYERS PARSED SUCCESSFULLY!")
    print("=" * 60)
    
except Exception as e:
    print(f"\n✗ Error: {e}")
    import traceback
    traceback.print_exc()
