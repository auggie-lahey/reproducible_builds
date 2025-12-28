#!/usr/bin/env python3
"""Test script for Zapstore validation."""

import sys
sys.path.insert(0, 'scripts')

from utils import validate_zapstore_app

# Test with org.fossify.calendar
relays = [
    "wss://relay.zapstore.dev"
]

print("Testing Zapstore app validation for org.fossify.calendar")
print("=" * 60)

result = validate_zapstore_app("org.fossify.calendar", relays, pubkey=None)

print("\n" + "=" * 60)
print("RESULT:")
print(f"  Valid: {result['valid']}")
print(f"  Error: {result['error']}")
if result['event']:
    print(f"  Event ID: {result['event'].get('id')}")
