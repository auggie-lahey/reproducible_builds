#!/usr/bin/env python3
"""
Main script to check reproducible builds and publish Nostr events.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import yaml
import requests

from utils import (
    fetch_izzy_log,
    parse_versions,
    detect_new_versions,
    update_state,
    load_template,
    replace_template_vars,
    create_event_id,
    format_timestamp
)


def load_config(config_path: str = "config.yaml") -> Dict:
    """Load configuration from YAML file."""
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def load_state(state_file: str = "state.json") -> Dict:
    """Load state from JSON file."""
    try:
        with open(state_file, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        # File exists but is empty or contains invalid JSON
        return {}


def save_state(state: Dict, state_file: str = "state.json"):
    """Save state to JSON file."""
    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)


def get_app_config(config: Dict, app_id: str) -> Optional[Dict]:
    """Get app configuration from config."""
    apps = config.get('apps', {})
    return apps.get(app_id)


def publish_nostr_event(event: Dict, nsec: str, relays: List[str], dry_run: bool = False) -> Optional[str]:
    """
    Publish Nostr event using nak.
    
    Args:
        event: Event dictionary to publish
        nsec: Nostr secret key
        relays: List of relay URLs
        dry_run: If True, echo event without publishing
    
    Returns:
        Event ID if successful, None otherwise
    """
    import subprocess
    import tempfile
    
    # Create temporary file for event
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(event, f)
        event_file = f.name
    
    try:
        # Echo event for review
        print("\n" + "="*60)
        print("EVENT TO PUBLISH:")
        print("="*60)
        print(json.dumps(event, indent=2))
        print("="*60 + "\n")
        
        if dry_run:
            print("DRY RUN: Event would be published (not actually publishing)")
            return create_event_id(event)
        
        # Use nak to publish
        relay_args = []
        for relay in relays:
            relay_args.extend(['--relay', relay])
        
        cmd = [
            'nak', 'event', 'publish',
            nsec,
            '--kind', str(event['kind']),
            '--content', event['content']
        ]
        
        # Add tags
        for tag in event.get('tags', []):
            if len(tag) >= 2:
                cmd.extend(['--tag', f"{tag[0]}={tag[1]}"])
        
        cmd.extend(relay_args)
        
        print(f"Publishing command: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode == 0:
            output = result.stdout.strip()
            print(f"✓ Event published successfully!")
            print(f"  Output: {output}")
            # Extract event ID from output (nak usually prints it)
            return output
        else:
            print(f"✗ Failed to publish event")
            print(f"  Error: {result.stderr}")
            return None
            
    except Exception as e:
        print(f"✗ Error publishing event: {e}")
        return None
    finally:
        # Clean up temp file
        try:
            Path(event_file).unlink()
        except:
            pass


def check_app(
    app_id: str,
    config: Dict,
    state: Dict,
    dry_run: bool = False
) -> List[Dict]:
    """
    Check a single app for new versions and publish events.
    
    Args:
        app_id: App identifier
        config: Configuration dictionary
        state: State dictionary
        dry_run: If True, don't actually publish
    
    Returns:
        List of published events (with metadata)
    """
    print(f"\n{'='*60}")
    print(f"Checking {app_id}")
    print(f"{'='*60}")
    
    # Get app configuration
    app_config = get_app_config(config, app_id)
    if not app_config:
        print(f"✗ App {app_id} not found in configuration")
        return []
    
    # Fetch log from Izzy
    print(f"Fetching log from IzzyOnDroid...")
    log_data = fetch_izzy_log(app_id)
    if not log_data:
        print(f"✗ Failed to fetch log for {app_id}")
        return []
    
    # Parse versions
    print(f"Parsing versions...")
    versions = parse_versions(log_data)
    print(f"  Found {len(versions)} versions")
    
    # Detect new versions
    new_versions = detect_new_versions(versions, state, app_id)
    print(f"  New versions since last check: {len(new_versions)}")
    
    if not new_versions:
        print("  No new versions to process")
        return []
    
    # Load templates
    assertion_template = load_template('templates/assertion.json')
    attestation_template = load_template('templates/attestation.json')
    
    # Get Nostr configuration
    nostr_config = config.get('nostr', {})
    nsec = nostr_config.get('nsec', '')
    relays = nostr_config.get('relays', [])
    
    if not nsec:
        print("✗ No nsec configured in config.yaml")
        print("  Generate one with: nak key gen")
        return []
    
    published_events = []
    
    # Process each new version
    for version in sorted(new_versions):
        print(f"\n  Processing version {version}...")
        
        # Get SHA256 hash for this version
        sha256_hashes = versions.get(version, [])
        if not sha256_hashes:
            print(f"    ✗ No SHA256 hash found for version {version}")
            continue
        
        sha256_hash = sha256_hashes[0]  # Use first hash
        
        # Determine reproducibility status
        # For now, if there's a hash in Izzy's log, it's reproducible
        is_reproducible = True
        
        # Prepare template variables
        import time
        timestamp = int(time.time())
        
        template_vars = {
            'app_id': app_id,
            'version': version,
            'commit_or_tag': app_config.get('commit_template', '').format(version=version),
            'sha256_hash': sha256_hash,
            'reproducible_status': 'reproducible' if is_reproducible else 'not reproducible',
            'architecture': app_config.get('arch', 'armeabi-v7a'),
            'timestamp': timestamp,
            'izzy_log_file': app_config.get('izzy_log_file', f'{app_id}.json')
        }
        
        # Create assertion event
        print(f"    Creating assertion event...")
        assertion_event = replace_template_vars(assertion_template, **template_vars)
        assertion_event['created_at'] = timestamp
        assertion_event['pubkey'] = extract_pubkey_from_nsec(nsec)
        
        assertion_id = create_event_id(assertion_event)
        assertion_event['id'] = assertion_id
        
        # Publish assertion
        assertion_result = publish_nostr_event(assertion_event, nsec, relays, dry_run)
        if not assertion_result and not dry_run:
            print(f"    ✗ Failed to publish assertion for {version}")
            continue
        
        print(f"    ✓ Assertion event ID: {assertion_id}")
        
        # Create attestation event
        print(f"    Creating attestation event...")
        attestation_vars = template_vars.copy()
        attestation_vars['assertion_event_id'] = assertion_id
        
        attestation_event = replace_template_vars(attestation_template, **attestation_vars)
        attestation_event['created_at'] = timestamp + 1  # Slightly later
        attestation_event['pubkey'] = extract_pubkey_from_nsec(nsec)
        
        attestation_id = create_event_id(attestation_event)
        attestation_event['id'] = attestation_id
        
        # Publish attestation
        attestation_result = publish_nostr_event(attestation_event, nsec, relays, dry_run)
        if not attestation_result and not dry_run:
            print(f"    ✗ Failed to publish attestation for {version}")
            continue
        
        print(f"    ✓ Attestation event ID: {attestation_id}")
        
        # Update state
        update_state(state, app_id, version, assertion_id)
        
        published_events.append({
            'app_id': app_id,
            'version': version,
            'assertion_id': assertion_id,
            'attestation_id': attestation_id,
            'reproducible': is_reproducible
        })
    
    return published_events


def extract_pubkey_from_nsec(nsec: str) -> str:
    """
    Extract npub (public key) from nsec (private key).
    
    For now, we'll use nak to decode it.
    """
    import subprocess
    
    try:
        result = subprocess.run(
            ['nak', 'key', 'public', nsec],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            print(f"Warning: Could not extract pubkey from nsec")
            return ""
    except Exception as e:
        print(f"Warning: Error extracting pubkey: {e}")
        return ""


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Check reproducible builds and publish Nostr events"
    )
    parser.add_argument(
        '--app',
        help='Specific app ID to check (default: all configured apps)'
    )
    parser.add_argument(
        '--config',
        default='config.yaml',
        help='Path to configuration file'
    )
    parser.add_argument(
        '--state',
        default='state.json',
        help='Path to state file'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Echo events without publishing'
    )
    
    args = parser.parse_args()
    
    # Load configuration
    try:
        config = load_config(args.config)
    except Exception as e:
        print(f"Error loading config: {e}")
        sys.exit(1)
    
    # Load state
    state = load_state(args.state)
    
    # Determine which apps to check
    if args.app:
        apps_to_check = [args.app]
    else:
        apps_to_check = list(config.get('apps', {}).keys())
    
    if not apps_to_check:
        print("No apps configured")
        sys.exit(1)
    
    print(f"Checking {len(apps_to_check)} app(s)...")
    
    # Check each app
    all_events = []
    for app_id in apps_to_check:
        try:
            events = check_app(app_id, config, state, args.dry_run)
            all_events.extend(events)
        except Exception as e:
            print(f"Error checking {app_id}: {e}")
            import traceback
            traceback.print_exc()
    
    # Save updated state
    if not args.dry_run:
        save_state(state, args.state)
        print(f"\nState saved to {args.state}")
    
    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"Apps checked: {len(apps_to_check)}")
    print(f"Events published: {len(all_events)}")
    
    if all_events:
        print("\nPublished events:")
        for event in all_events:
            status = "✓" if event['reproducible'] else "✗"
            print(f"  {status} {event['app_id']} {event['version']}")
            print(f"      Assertion: {event['assertion_id']}")
            print(f"      Attestation: {event['attestation_id']}")
    
    print()


if __name__ == "__main__":
    main()
