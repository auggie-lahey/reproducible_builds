#!/usr/bin/env python3
"""Test subprocess output capture from nak command."""

import subprocess
import sys

print("Testing nak output capture...")
print("=" * 60)

# Test 1: Basic capture with default settings
print("\nTest 1: capture_output=True, timeout=15")
cmd = ['nak', 'req', '-k', '32267', 'wss://relay.zapstore.dev']
result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)

print(f"Return code: {result.returncode}")
print(f"STDOUT length: {len(result.stdout)} bytes, {len(result.stdout.splitlines())} lines")
print(f"STDERR length: {len(result.stderr)} bytes")
print(f"First 100 chars of stdout: {result.stdout[:100]}")
print(f"Last 100 chars of stdout: {result.stdout[-100:]}")

# Count actual JSON events
event_count = 0
for line in result.stdout.strip().split('\n'):
    if line.strip():
        try:
            import json
            json.loads(line)
            event_count += 1
        except json.JSONDecodeError:
            pass

print(f"Valid JSON events found: {event_count}")

# Test 2: With explicit PIPE
print("\n" + "=" * 60)
print("\nTest 2: stdout=PIPE, stderr=PIPE")
result2 = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)

print(f"Return code: {result2.returncode}")
print(f"STDOUT length: {len(result2.stdout)} bytes, {len(result2.stdout.splitlines())} lines")
print(f"STDERR length: {len(result2.stderr)} bytes")

# Count events
event_count2 = 0
for line in result2.stdout.strip().split('\n'):
    if line.strip():
        try:
            import json
            json.loads(line)
            event_count2 += 1
        except json.JSONDecodeError:
            pass

print(f"Valid JSON events found: {event_count2}")

# Test 3: Check if they match
print("\n" + "=" * 60)
if result.stdout == result2.stdout:
    print("✅ Both methods captured identical output")
else:
    print("❌ Methods captured different output!")
    print(f"Difference in length: {abs(len(result.stdout) - len(result2.stdout))} bytes")
