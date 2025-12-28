#!/usr/bin/env python3
"""
Utility functions for reproducible build attestation system.
"""

import json
import requests
import hashlib
from typing import Dict, List, Optional, Any
from pathlib import Path


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
            placeholder = f"{{{{ {key} }}}}"
            template_var = f"{{{{ {key.upper()} }}}}"
            content = content.replace(placeholder, str(value))
            content = content.replace(template_var, str(value))
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
                    placeholder = f"{{{{ {key} }}}}"
                    template_var = f"{{{{ {key.upper()} }}}}"
                    replaced_item = replaced_item.replace(placeholder, str(value))
                    replaced_item = replaced_item.replace(template_var, str(value))
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


if __name__ == "__main__":
    # Test fetching a log
    log = fetch_izzy_log("org.fossify.calendar")
    if log:
        print(f"App ID: {log.get('appid')}")
        versions = parse_versions(log)
        print(f"Found {len(versions)} versions")
        for version, hashes in list(versions.items())[:3]:
            print(f"  {version}: {len(hashes)} hash(es)")
