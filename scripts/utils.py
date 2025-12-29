#!/usr/bin/env python3
"""
Utility functions for reproducible build attestation system.
"""

import json
import requests
import hashlib
from typing import Dict, List, Optional, Any
from pathlib import Path


def fetch_app_definition_from_relay(zapstore_appid: str, relays: List[str], pubkey: Optional[str] = None) -> Optional[Dict]:
    """
    Fetch app definition event from Nostr relay using d tag.
    
    Args:
        zapstore_appid: App identifier for Zapstore
        relays: List of relay URLs
        pubkey: Optional pubkey to filter specific app definition
    
    Returns:
        App definition event or None
    """
    import subprocess
    import json
    
    try:
        # Build nak req command to find app definition
        # Kind 32267 is for Zapstore app definitions
        cmd = [
            'nak', 'req',
            '--kind', '32267',
            '--tag', f'd={zapstore_appid}',
            relays[0]  # Use first relay
        ]
        
        if pubkey:
            cmd.extend(['--author', pubkey])
        
        cmd.extend(['--limit', '1'])
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            # Parse JSON output
            lines = result.stdout.strip().split('\n')
            for line in lines:
                try:
                    event = json.loads(line)
                    if event.get('kind') == 32267:
                        print(f"    ✓ Found app definition for {zapstore_appid}")
                        return event
                except json.JSONDecodeError:
                    continue
        else:
            print(f"    ✗ Failed to fetch app definition: {result.stderr}")
        
        return None
    except Exception as e:
        print(f"    ✗ Error fetching app definition: {e}")
        return None


def fetch_release_events_from_relay(app_definition_event: Dict, relays: List[str]) -> List[Dict]:
    """
    Fetch release events referenced by app definition.
    
    Args:
        app_definition_event: The app definition event (kind 32267)
        relays: List of relay URLs
    
    Returns:
        List of release events
    """
    import subprocess
    import json
    
    try:
        # Get the pubkey and app id from app definition
        pubkey = app_definition_event.get('pubkey')
        if not pubkey:
            print(f"    ✗ No pubkey in app definition")
            return []
        
        # Get the app_id from the app definition's d tag
        app_id = None
        for tag in app_definition_event.get('tags', []):
            if len(tag) >= 2 and tag[0] == 'd':
                app_id = tag[1]
                break
        
        if not app_id:
            print(f"    ✗ No app id in app definition")
            return []
        
        # Query for kind 30063 (Android app releases) 
        # Filter by the 'a' tag which references the app definition
        # a tag format: 32267:pubkey:app_id
        a_tag = f"32267:{pubkey}:{app_id}"
        
        # Prefer zapstore relay for release events, otherwise use first relay
        relay = next((r for r in relays if 'zapstore' in r), relays[0])
        
        cmd = [
            'nak', 'req',
            '--kind', '30063',
            '--tag', f'a={a_tag}',
            relay
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            release_events = []
            lines = result.stdout.strip().split('\n')
            for line in lines:
                try:
                    event = json.loads(line)
                    # Just add all kind 30063 events - they're already filtered by a tag
                    if event.get('kind') == 30063:
                        release_events.append(event)
                except json.JSONDecodeError:
                    continue
            
            print(f"    ✓ Found {len(release_events)} release events for {app_id}")
            return release_events
        else:
            print(f"    ✗ Failed to fetch release events: {result.stderr}")
        
        return []
    except Exception as e:
        print(f"    ✗ Error fetching release events: {e}")
        return []


def find_release_for_version(release_events: List[Dict], version: str) -> Optional[Dict]:
    """
    Find release event for specific version.
    
    Args:
        release_events: List of release events
        version: Version string to match
    
    Returns:
        Matching release event or None
    """
    for event in release_events:
        tags = event.get('tags', [])
        tag_dict = {tag[0]: tag[1] if len(tag) > 1 else None for tag in tags}
        
        # Check commit tag (where version is often stored)
        if tag_dict.get('commit') == version:
            return event
        
        # Check version tag
        if tag_dict.get('version') == version:
            return event
        
        # Check d tag for version pattern (e.g., "appid@version")
        d_value = tag_dict.get('d', '')
        if f'@{version}' in d_value or f'v{version}' in d_value:
            return event
        
        # Check if version is in content
        content = event.get('content', '')
        if version in content:
            return event
    
    return None


def fetch_izzy_log(app_id: str, base_url: str = "https://codeberg.org/api/v1/repos") -> Optional[Dict]:
    """
    Fetch reproducible build log from IzzyOnDroid's rbtlog repository.
    
    Args:
        app_id: App identifier (e.g., "org.fossify.calendar")
        base_url: Base URL for Codeberg API
    
    Returns:
        Parsed JSON data or None if fetch fails
    """
    log_file = f"{app_id}.json"
    url = f"{base_url}/IzzyOnDroid/rbtlog/contents/logs/{log_file}"
    
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        # Decode base64 content
        import base64
        content = base64.b64decode(data['content']).decode('utf-8')
        return json.loads(content)
    except Exception as e:
        print(f"Error fetching log for {app_id}: {e}")
        return None


def parse_versions(log_data: Dict) -> Dict[str, List[str]]:
    """
    Parse version codes from Izzy's log format.
    
    The log format is:
    {
      "appid": "org.fossify.calendar",
      "sha256": {
        "hash1": ["1.0.3"],
        "hash2": ["1.1.0", "1.1.1"]
      },
      "version_codes": {...},
      "tags": {...}
    }
    
    Args:
        log_data: Parsed JSON from Izzy's log
    
    Returns:
        Dictionary mapping version -> list of SHA256 hashes
    """
    versions = {}
    
    if not log_data or 'sha256' not in log_data:
        return versions
    
    sha256_data = log_data['sha256']
    
    for sha256_hash, version_list in sha256_data.items():
        for version in version_list:
            if version not in versions:
                versions[version] = []
            versions[version].append(sha256_hash)
    
    return versions


def detect_new_versions(
    current_versions: Dict[str, List[str]],
    state: Dict[str, str],
    app_id: str
) -> List[str]:
    """
    Detect new versions by comparing with stored state.
    
    Args:
        current_versions: Current versions from log (version -> hashes)
        state: Stored state from previous runs
        app_id: App identifier
    
    Returns:
        List of new version numbers
    """
    last_checked = state.get(app_id, {})
    new_versions = []
    
    for version in current_versions.keys():
        if version not in last_checked:
            new_versions.append(version)
    
    return new_versions


def update_state(state: Dict, app_id: str, version: str, event_id: str = "") -> Dict:
    """
    Update state with newly checked version.
    
    Args:
        state: Current state dictionary
        app_id: App identifier
        version: Version number
        event_id: Optional Nostr event ID
    
    Returns:
        Updated state dictionary
    """
    if app_id not in state:
        state[app_id] = {}
    
    state[app_id][version] = {
        "checked": True,
        "event_id": event_id
    }
    
    return state


def load_template(template_path: str) -> Dict:
    """
    Load JSON template file.
    
    Args:
        template_path: Path to template file
    
    Returns:
        Parsed template dictionary
    """
    template_file = Path(template_path)
    
    if not template_file.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")
    
    with open(template_file, 'r') as f:
        return json.load(f)


def replace_template_vars(template: Dict, **kwargs) -> Dict:
    """
    Replace template variables with actual values.
    
    Supports both string replacements in JSON values and tag arrays.
    
    Args:
        template: Template dictionary
        **kwargs: Key-value pairs for replacement
    
    Returns:
        Dictionary with replaced values
    """
    import copy
    
    result = copy.deepcopy(template)
    
    # Replace in content
    if 'content' in result:
        content = result['content']
        for key, value in kwargs.items():
            # Try both formats: {{KEY}} and {{ key }}
            template_var_upper = f"{{{{{key.upper()}}}}}"
            template_var_lower = f"{{{{{key}}}}}"
            template_var_upper_space = f"{{{{ {key.upper()} }}}}"
            template_var_lower_space = f"{{{{ {key} }}}}"
            
            content = content.replace(template_var_upper, str(value))
            content = content.replace(template_var_lower, str(value))
            content = content.replace(template_var_upper_space, str(value))
            content = content.replace(template_var_lower_space, str(value))
        result['content'] = content
    
    # Replace in tags
    if 'tags' in result:
        new_tags = []
        for tag in result['tags']:
            new_tag = []
            for item in tag:
                # Try to replace any template variables
                replaced_item = item
                for key, value in kwargs.items():
                    # Try both formats: {{KEY}} and {{ key }}
                    template_var_upper = f"{{{{{key.upper()}}}}}"
                    template_var_lower = f"{{{{{key}}}}}"
                    template_var_upper_space = f"{{{{ {key.upper()} }}}}"
                    template_var_lower_space = f"{{{{ {key} }}}}"
                    
                    replaced_item = replaced_item.replace(template_var_upper, str(value))
                    replaced_item = replaced_item.replace(template_var_lower, str(value))
                    replaced_item = replaced_item.replace(template_var_upper_space, str(value))
                    replaced_item = replaced_item.replace(template_var_lower_space, str(value))
                new_tag.append(replaced_item)
            new_tags.append(new_tag)
        result['tags'] = new_tags
    
    return result


def create_event_id(event: Dict) -> str:
    """
    Create Nostr event ID by serializing and hashing.
    
    Args:
        event: Event dictionary
    
    Returns:
        Hex string of event ID
    """
    import copy
    
    # Create a copy without the id and sig fields
    event_copy = copy.deepcopy(event)
    event_copy.pop('id', None)
    event_copy.pop('sig', None)
    
    # Serialize according to Nostr protocol
    # [0, pubkey, created_at, kind, tags, content]
    serialized = json.dumps([
        0,
        event_copy.get('pubkey', ''),
        event_copy.get('created_at', 0),
        event_copy.get('kind', 0),
        event_copy.get('tags', []),
        event_copy.get('content', '')
    ], separators=(',', ':'))
    
    # SHA256 hash
    return hashlib.sha256(serialized.encode()).hexdigest()


def format_timestamp(timestamp: Optional[int] = None) -> str:
    """
    Format timestamp for display.
    
    Args:
        timestamp: Unix timestamp (default: current time)
    
    Returns:
        ISO 8601 formatted string
    """
    import datetime
    
    if timestamp is None:
        timestamp = int(datetime.datetime.now().timestamp())
    
    dt = datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc)
    return dt.isoformat()


def fetch_zapstore_app_def(
    zapstore_appid: str,
    relays: List[str],
    pubkey: Optional[str] = None
) -> List[Dict]:
    """
    Fetch Zapstore app definition (kind 32267) from Nostr relays.
    
    Args:
        zapstore_appid: Zapstore app identifier (d tag value)
        relays: List of Nostr relay URLs
        pubkey: Optional pubkey to filter by
    
    Returns:
        List of matching kind 32267 events
    """
    import subprocess
    
    matching_events = []
    
    print(f"  Querying {len(relays)} relay(s) for app definition...")
    
    for relay in relays:
        try:
            print(f"    Checking {relay}...")
            # Build nak command to query for kind 32267 with specific d tag
            cmd = [
                'nak', 'req',
                '-k', '32267',
                '-d', zapstore_appid,
                relay
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                print(f"      ✗ Query failed: {result.stderr}")
                continue
            
            # Check if we got any output
            if not result.stdout.strip():
                print(f"      ✗ No response from relay")
                continue
            
            # Parse output - relay returns newline-delimited JSON
            line_count = 0
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                
                line_count += 1
                try:
                    event = json.loads(line)
                    
                    # Verify it's a kind 32267 event
                    if event.get('kind') != 32267:
                        continue
                    
                    # Check d tag matches
                    tags = event.get('tags', [])
                    d_tag_value = None
                    for tag in tags:
                        if len(tag) >= 2 and tag[0] == 'd':
                            d_tag_value = tag[1]
                            break
                    
                    if d_tag_value != zapstore_appid:
                        continue
                    
                    # If pubkey specified, filter by it
                    if pubkey and event.get('pubkey') != pubkey:
                        continue
                    
                    # Deduplicate by event ID
                    event_id = event.get('id')
                    if not any(e.get('id') == event_id for e in matching_events):
                        print(f"      ✓ Found matching event: {event_id[:8]}...")
                        matching_events.append(event)
                        
                except json.JSONDecodeError as e:
                    print(f"      ✗ Failed to parse JSON: {e}")
                    continue
            
            if line_count == 0:
                print(f"      ✗ No events returned")
            elif len(matching_events) == 0:
                print(f"      ✗ {line_count} event(s) returned, but none matched")
                    
        except subprocess.TimeoutExpired:
            print(f"      ✗ Query timed out after 30s")
            continue
        except Exception as e:
            print(f"      ✗ Error: {e}")
            continue
    
    return matching_events


def validate_zapstore_app(
    zapstore_appid: str,
    relays: List[str],
    pubkey: Optional[str] = None
) -> Dict:
    """
    Validate Zapstore app definition exists and is unique.
    
    Args:
        zapstore_appid: Zapstore app identifier (d tag value)
        relays: List of Nostr relay URLs
        pubkey: Optional pubkey to filter by
    
    Returns:
        Dictionary with validation result:
        {
            'valid': bool,
            'event': Dict or None,
            'error': str or None
        }
    
    Validation logic:
    - 0 results → Error: App definition not found
    - 1 result → Use it
    - 2+ results → 
        - If pubkey specified → Filter by pubkey
            - 1 result → Use it
            - 0 results → Error: No matching event from specified pubkey
        - If no pubkey → Error: Multiple definitions found
    """
    print(f"\nValidating Zapstore app '{zapstore_appid}'...")
    
    # Fetch all matching events
    events = fetch_zapstore_app_def(zapstore_appid, relays, pubkey)
    
    # Case 1: No events found
    if len(events) == 0:
        return {
            'valid': False,
            'event': None,
            'error': f"App definition not found for '{zapstore_appid}' on configured relays"
        }
    
    # Case 2: Exactly one event found
    if len(events) == 1:
        event = events[0]
        event_id = event.get('id', 'unknown')
        event_pubkey = event.get('pubkey', 'unknown')
        
        # Extract app name from tags
        tags = event.get('tags', [])
        app_name = zapstore_appid
        for tag in tags:
            if len(tag) >= 2 and tag[0] == 'name':
                app_name = tag[1]
                break
        
        print(f"  ✓ Found app definition: {app_name}")
        print(f"    Event ID: {event_id}")
        print(f"    Pubkey: {event_pubkey}")
        
        return {
            'valid': True,
            'event': event,
            'error': None
        }
    
    # Case 3: Multiple events found
    if len(events) > 1:
        if pubkey:
            # Pubkey was specified but we still got multiple events
            # This shouldn't happen if fetch_zapstore_app_def filtered correctly
            # but handle it just in case
            return {
                'valid': False,
                'event': None,
                'error': f"Multiple app definitions found even with pubkey filter. This should not happen."
            }
        else:
            # No pubkey specified and multiple events found
            print(f"  ✗ Found {len(events)} app definitions:")
            for i, event in enumerate(events, 1):
                event_id = event.get('id', 'unknown')
                event_pubkey = event.get('pubkey', 'unknown')
                
                # Try to extract app name
                tags = event.get('tags', [])
                app_name = zapstore_appid
                for tag in tags:
                    if len(tag) >= 2 and tag[0] == 'name':
                        app_name = tag[1]
                        break
                
                print(f"    {i}. {app_name}")
                print(f"       Event ID: {event_id}")
                print(f"       Pubkey: {event_pubkey}")
            
            return {
                'valid': False,
                'event': None,
                'error': (
                    f"Found {len(events)} app definitions for '{zapstore_appid}'.\n"
                    f"Please specify 'zapstore_pubkey' in config.yaml to select which one to use."
                )
            }
    
    # Should never reach here
    return {
        'valid': False,
        'event': None,
        'error': 'Unknown validation error'
    }


if __name__ == "__main__":
    # Test fetching a log
    log = fetch_izzy_log("org.fossify.calendar")
    if log:
        print(f"App ID: {log.get('appid')}")
        versions = parse_versions(log)
        print(f"Found {len(versions)} versions")
        for version, hashes in list(versions.items())[:3]:
            print(f"  {version}: {len(hashes)} hash(es)")
