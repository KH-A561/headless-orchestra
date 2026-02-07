"""Тест базового вызова Anthropic API."""

import os
from anthropic import Anthropic

api_key = os.getenv("ANTHROPIC_API_KEY")
if not api_key:
    print("ERROR: ANTHROPIC_API_KEY not set")
    exit(1)

print(f"API key found: {api_key[:10]}...")

try:
    print("Creating Anthropic client...")
    client = Anthropic(api_key=api_key)
    print("✓ Client created")

    print("Calling API...")
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=100,
        messages=[{"role": "user", "content": "Say hello"}],
    )
    print("✓ API call successful")
    print(f"Response: {response.content[0].text}")

except Exception as e:
    print(f"✗ Error: {e}")
    import traceback

    traceback.print_exc()
