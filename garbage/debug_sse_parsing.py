"""Debug script with SSE parsing."""

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

headers = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream"
}

def parse_sse_response(sse_text):
    """Parse Server-Sent Events format."""
    lines = sse_text.strip().split('\n')
    data_lines = []
    
    for line in lines:
        if line.startswith('data: '):
            # Extract data after "data: " prefix
            data_lines.append(line[6:])
    
    # Join all data lines
    json_str = ''.join(data_lines)
    
    if not json_str:
        raise ValueError("No data found in SSE response")
    
    return json.loads(json_str)

print("=" * 60)
print("DEBUG: Producer Pal with SSE parsing")
print("=" * 60)

try:
    response = requests.post(url, json=payload, headers=headers, timeout=30)
    
    print(f"\n[1] Status: {response.status_code}")
    print(f"    Content-Type: {response.headers.get('Content-Type')}")
    
    content_type = response.headers.get('Content-Type', '')
    
    if 'text/event-stream' in content_type:
        print("\n[2] Parsing SSE format...")
        print(f"    Raw SSE (first 300 chars):\n{response.text[:300]}")
        
        data = parse_sse_response(response.text)
        print("\n[3] ✓ SSE parsed successfully!")
        
        if "result" in data:
            result = data["result"]
            print(f"\n[4] Result structure:")
            print(f"    Keys: {list(result.keys())}")
            
            # If there's 'content', extract it
            if "content" in result:
                content = result["content"]
                if content and isinstance(content, list) and len(content) > 0:
                    first_item = content[0]
                    if first_item.get("type") == "text":
                        # Parse the inner text JSON
                        inner_json_str = first_item.get("text", "")
                        print(f"\n[5] Inner content (first 500 chars):")
                        print(inner_json_str[:500])
                        
                        # Try to parse inner JSON (it might be a JSON string)
                        # Note: The text might be JSON with unquoted keys - need to handle that
                        print(f"\n[6] This looks like JSON with unquoted keys")
                        print("    Producer Pal returns nested JSON in 'text' field")
        else:
            print(json.dumps(data, indent=2))
    else:
        print("\n[2] Parsing regular JSON...")
        data = response.json()
        print(json.dumps(data, indent=2))
        
except Exception as e:
    print(f"\n✗ Error: {e}")
    import traceback
    traceback.print_exc()
