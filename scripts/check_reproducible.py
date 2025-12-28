#!/usr/bin/env python3
"""
Main script to check reproducible builds and publish Nostr events.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import yaml
import requests

from utils import (
    fetch_izzy_log,
    parse_versions,
    load_template,
    replace_template_vars,
    create_event_id,
    format_timestamp,
    validate_zapstore_app,
    fetch_app_definition_from_relay,
    fetch_release_events_from_relay,
    find_release_for_version
)


def load_config(config_path: str = "config.yaml") -> Dict:
    """Load configuration from YAML file."""
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def test_relay_connectivity(relays: List[str]) -> bool:
    """
    Test connectivity to all configured relays and fetch app definition count.
    
    This helps diagnose network issues in CI environments.
    
    Returns:
        bool: True if at least one relay connected successfully, False otherwise
    """
    import subprocess
    import sys
    
    print(f"\n{'='*60}")
    print("TESTING RELAY CONNECTIVITY")
    print(f"{'='*60}")
    
    # Check if nak is available
    try:
        nak_check = subprocess.run(['nak', '--version'], 
                                  capture_output=True, 
                                  text=True, 
                                  timeout=5)
        print(f"Using nak version: {nak_check.stdout.strip()}")
    except Exception as e:
        print(f"✗ ERROR: nak command not found: {e}")
        print("  Please ensure nak is installed and in PATH")
        return False
    
    print(f"Testing {len(relays)} relay(s)...\n")
    
    successful_connections = 0
    
    for relay in relays:
        try:
            print(f"  Testing {relay}...")
            
            # Test 1: Basic connection with a simple query
            cmd = ['nak', 'req', '-k', '32267', '--limit', '1', relay]
            print(f"    Command: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15
            )
            print(result)
            if result.returncode != 0:
                print(f"    ✗ Connection failed (exit code {result.returncode})")
                print(f"    STDERR: {result.stderr[:200]}")
                print(f"    STDOUT: {result.stdout[:200]}")
                continue
            
            # Test 2: Count all kind 32267 events
            cmd_count = ['nak', 'req', '-k', '32267', relay]
            result_count = subprocess.run(
                cmd_count,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result_count.returncode != 0:
                print(f"    ✗ Query failed (exit code {result_count.returncode})")
                print(f"    STDERR: {result_count.stderr[:200]}")
                continue
            
            # Count events
            event_count = 0
            for line in result_count.stdout.strip().split('\n'):
                if line.strip():
                    try:
                        json.loads(line)
                        event_count += 1
                    except json.JSONDecodeError:
                        pass
            
            if event_count > 0:
                print(f"    ✓ Connected - Found {event_count} app definition(s)")
                successful_connections += 1
            else:
                print(f"    ✓ Connected - No app definitions found")
                successful_connections += 1
                
        except subprocess.TimeoutExpired:
            print(f"    ✗ Timeout after 15s - relay may be blocking GitHub Actions IPs")
        except FileNotFoundError:
            print(f"    ✗ ERROR: nak command not found")
            print(f"    Ensure nak is installed and in PATH")
            return False
        except Exception as e:
            print(f"    ✗ Unexpected error: {str(e)[:200]}")
            import traceback
            print(f"    Traceback: {traceback.format_exc()[:200]}")
    
    print()
    
    # Fail if no relays could be reached
    if successful_connections == 0:
        print("✗ CRITICAL: No relays could be reached!")
        print("  This appears to be a network connectivity issue.")
        print("  Possible causes:")
        print("    - GitHub Actions IPs are being blocked by relays")
        print("    - Firewall or network restrictions")
        print("    - Relays are down")
        print("  Consider using a self-hosted runner or VPN/proxy.")
        print("\n  TIP: Run 'nak req -k 32267 wss://relay.zapstore.dev' locally to verify")
        return False
    
    print(f"✓ Successfully connected to {successful_connections}/{len(relays)} relay(s)")
    return True


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
        
        # Build nak event command
        # nak event --sec <nsec> --kind <kind> --content <content> --tag <tag>... <relay1> <relay2>...
        cmd = [
            'nak', 'event', '--quiet',
            '--sec', nsec,
            '--kind', str(event['kind']),
            '--content', event['content']
        ]
        
        # Add tags (use -t flag for tags)
        for tag in event.get('tags', []):
            if len(tag) >= 2:
                cmd.extend(['--tag', f"{tag[0]}={tag[1]}"])
        
        # Add relays as positional arguments at the end
        cmd.extend(relays)
        
        #print(f"Publishing command: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode == 0:
            output = result.stdout.strip()
            print(f"✓ Event published successfully!")
            #print(f"  Output: {output}")
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
    dry_run: bool = False
) -> List[Dict]:
    """
    Check a single app and publish events for the latest version.
    
    Args:
        app_id: App identifier
        config: Configuration dictionary
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
    
    # Validate Zapstore app definition
    zapstore_appid = app_config.get('zapstore_appid')
    if not zapstore_appid:
        print(f"✗ No zapstore_appid configured for {app_id}")
        return []
    
    nostr_config = config.get('nostr', {})
    relays = nostr_config.get('relays', [])
    zapstore_pubkey = app_config.get('zapstore_pubkey')
    
    validation = validate_zapstore_app(zapstore_appid, relays, zapstore_pubkey)
    
    if not validation['valid']:
        print(f"✗ Zapstore validation failed: {validation['error']}")
        return []
    
    # Store the app definition event for later use
    app_def_event = validation['event']
    
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
    
    if not versions:
        print("  No versions found")
        return []
    
    # Always process the latest version (highest version number)
    latest_version = sorted(versions.keys(), reverse=True)[0]
    print(f"  Latest version: {latest_version}")
    
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
    
    # Fetch release events from the app definition we already have
    release_event = None
    release_coordinate = ""
    release_event_id = ""
    
    if app_def_event:
        print(f"\n  Fetching release events from app definition...")
        release_events = fetch_release_events_from_relay(app_def_event, relays)
        release_event = find_release_for_version(release_events, latest_version)
        
        if release_event:
            # Build coordinate: <kind>:<pubkey>:<d-tag-value>
            coord_kind = release_event.get('kind', 30818)
            coord_pubkey = release_event.get('pubkey', '')
            coord_d = latest_version  # or extract from tags
            release_coordinate = f"{coord_kind}:{coord_pubkey}:{coord_d}"
            release_event_id = release_event.get('id', '')
            print(f"    ✓ Found release event for version {latest_version}")
            print(f"      Coordinate: {release_coordinate}")
            print(f"      Event ID: {release_event_id}")
        else:
            print(f"    ✗ No release event found for version {latest_version}")
            print(f"    ✗ Cannot create assertion without linking to a release event")
            print(f"    ✗ Please ensure Zapstore has published a release event for this app/version")
            return []
    else:
        print(f"    ✗ No app definition found")
        return []
    
    # Process only the latest version
    print(f"\n  Processing latest version {latest_version}...")
    
    # Get SHA256 hash for this version
    sha256_hashes = versions.get(latest_version, [])
    if not sha256_hashes:
        print(f"    ✗ No SHA256 hash found for version {latest_version}")
        return []
    
    sha256_hash = sha256_hashes[0]  # Use first hash
    
    # Determine reproducibility status
    # For now, if there's a hash in Izzy's log, it's reproducible
    is_reproducible = True
    
    # Prepare template variables
    import time
    timestamp = int(time.time())
    
    template_vars = {
        'app_id': app_id,
        'version': latest_version,
        'commit_or_tag': app_config.get('commit_template', '').format(version=latest_version),
        'sha256_hash': sha256_hash,
        'reproducible_status': 'true' if is_reproducible else 'false',
        'architecture': app_config.get('arch', 'armeabi-v7a'),
        'timestamp': timestamp,
        'izzy_log_file': app_config.get('izzy_log_file', f'{app_id}.json'),
        'release_event_id': release_event_id if release_event_id else ''
    }
    
    # Only add release coordinate if we found one
    if release_coordinate:
        template_vars['release_event_coordinate'] = release_coordinate
    
    # Create assertion event
    print(f"    Creating assertion event...")
    assertion_event = replace_template_vars(assertion_template, **template_vars)
    assertion_event['created_at'] = timestamp
    assertion_event['pubkey'] = extract_pubkey_from_nsec(nsec)
    
    # Add 'a' tag if we have a release coordinate
    if release_coordinate:
        assertion_event['tags'].append(['a', release_coordinate])
    
    assertion_id = create_event_id(assertion_event)
    assertion_event['id'] = assertion_id
    
    # Publish assertion
    assertion_result = publish_nostr_event(assertion_event, nsec, relays, dry_run)
    if not assertion_result and not dry_run:
        print(f"    ✗ Failed to publish assertion for {latest_version}")
        return []
    
    print(f"    ✓ Assertion event ID: {assertion_id}")
    
    # Create attestation event
    print(f"    Creating attestation event...")
    attestation_vars = template_vars.copy()
    attestation_vars['assertion_event_id'] = assertion_id
    attestation_vars['npub'] = extract_pubkey_from_nsec(nsec)
    # Map reproducible_status to validity
    attestation_vars['validity'] = 'valid' if is_reproducible else 'invalid'
    
    attestation_event = replace_template_vars(attestation_template, **attestation_vars)
    attestation_event['created_at'] = timestamp + 1  # Slightly later
    attestation_event['pubkey'] = extract_pubkey_from_nsec(nsec)
    
    attestation_id = create_event_id(attestation_event)
    attestation_event['id'] = attestation_id
    
    # Publish attestation
    attestation_result = publish_nostr_event(attestation_event, nsec, relays, dry_run)
    if not attestation_result and not dry_run:
        print(f"    ✗ Failed to publish attestation for {latest_version}")
        return []
    
    print(f"    ✓ Attestation event ID: {attestation_id}")
    
    published_events.append({
        'app_id': app_id,
        'version': latest_version,
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
        '--dry-run',
        action='store_true',
        help='Echo events without publishing'
    )
    
    args = parser.parse_args()
    
    # Verify nak is installed
    try:
        result = subprocess.run(['nak', '--version'], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            print("Error: nak CLI is not installed or not working")
            print("Install it from: https://github.com/fiatjaf/nak/releases")
            sys.exit(1)
        print(f"Using nak version: {result.stdout.strip()}")
    except Exception as e:
        print(f"Error checking nak installation: {e}")
        print("Please install nak from: https://github.com/fiatjaf/nak/releases")
        sys.exit(1)
    
    # Load configuration
    try:
        config = load_config(args.config)
    except Exception as e:
        print(f"Error loading config: {e}")
        sys.exit(1)
    
    # Test relay connectivity before starting
    nostr_config = config.get('nostr', {})
    relays = nostr_config.get('relays', [])
    if relays:
        connectivity_ok = test_relay_connectivity(relays)
        if not connectivity_ok:
            print("\n✗ Cannot proceed without relay connectivity")
            sys.exit(1)
    
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
    failed_apps = []
    for app_id in apps_to_check:
        try:
            events = check_app(app_id, config, args.dry_run)
            if not events:
                # check_app returned empty list, which means it failed
                failed_apps.append(app_id)
            else:
                all_events.extend(events)
        except Exception as e:
            print(f"Error checking {app_id}: {e}")
            import traceback
            traceback.print_exc()
            failed_apps.append(app_id)
    
    # Fail if any apps failed to process
    if failed_apps:
        print(f"\n✗ Failed to process {len(failed_apps)} app(s): {', '.join(failed_apps)}")
        sys.exit(1)
    
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
