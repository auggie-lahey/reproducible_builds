# Reproducible Build Attestation System

Automated system to monitor [IzzyOnDroid/rbtlog](https://codeberg.org/IzzyOnDroid/rbtlog) and publish Nostr events for reproducible build attestations.

## Overview

This project piggybacks on the IzzyOnDroid reproducible build logs to automatically create Nostr events when:
- An app has a new release verified as reproducible
- An app has a new release that fails reproducibility checks

For each release, two Nostr events are created:
1. **Assertion Event**: Declares whether the build is reproducible (or not)
2. **Attestation Event**: Confirms that the assertion is true

## Project Structure

```
.
├── config.yaml                    # Configuration file
├── templates/
│   ├── assertion.json            # Nostr assertion event template
│   └── attestation.json          # Nostr attestation event template
├── scripts/
│   ├── check_reproducible.py     # Main script to check and publish
│   └── utils.py                  # Utility functions
├── .github/
│   └── workflows/
│       └── reproducible.yml      # GitHub Actions workflow
├── state.json                    # Tracks last checked versions
└── README.md                     # This file
```

## Setup

### Prerequisites

- Python 3.9+
- GitHub account
- Nostr keys (generated via `nak`)

### Installation

1. Clone this repository
2. Install dependencies: `pip install -r requirements.txt`
3. Configure `config.yaml` with your settings
4. Generate Nostr keys: `nak key gen` (add to config)

## Configuration

Edit `config.yaml`:

```yaml
nostr:
  nsec: "your-nsec-key-here"
  relays:
    - "wss://relay.damus.io"
    - "wss://relay.primal.net"

apps:
  # Zapstore app ID -> IzzyOnDroid app ID mapping
  org.fossify.calendar:
    izzy_appid: "org.fossify.calendar"
    zapstore_appid: "calendar"  # or appropriate zapstore ID
    
github:
  # IzzyOnDroid repo for reproducible build logs
  rbtlog_repo: "https://codeberg.org/IzzyOnDroid/rbtlog"
  base_url: "https://codeberg.org/api/v1/repos"
```

## Nostr Event Format

Based on [zapstore issue #23](https://github.com/zapstore/zapstore/issues/23):

### Assertion Event (Kind 1063)

```json
{
  "kind": 1063,
  "tags": [
    ["d", "{{APP_ID}}"],
    ["version", "{{VERSION}}"],
    ["commit", "{{COMMIT_OR_TAG}}"],
    ["sha256", "{{SHA256_HASH}}"],
    ["reproducible", "{{true|false}}"],
    ["arch", "{{ARCHITECTURE}}"]
  ],
  "content": "{{APP_ID}} {{VERSION}} is {{REPRODUCIBLE_STATUS}}"
}
```

### Attestation Event (Kind 1063)

```json
{
  "kind": 1063,
  "tags": [
    ["d", "{{APP_ID}}"],
    ["attestation", "{{ASSERTION_EVENT_ID}}"]
  ],
  "content": "I attest that the reproducibility assertion for {{APP_ID}} {{VERSION}} is true"
}
```

## Usage

### Manual Execution

```bash
python scripts/check_reproducible.py --app org.fossify.calendar
```

### GitHub Actions

The workflow runs automatically on schedule (default: daily). You can also trigger it manually:

1. Go to Actions tab in GitHub
2. Select "Reproducible Build Checker"
3. Click "Run workflow"

## Development

### Testing

```bash
# Test with a specific app
python scripts/check_reproducible.py --app org.fossify.calendar --dry-run

# Parse a log file
python scripts/utils.py --parse-log logs/org.fossify.calendar.json
```

## References

- [Zapstore Issue #23 - Reproducibility Attestation](https://github.com/zapstore/zapstore/issues/23)
- [Attestation Discussion on Nostr](https://nostrhub.io/naddr1qvzqqqrcvypzp384u7n44r8rdq74988lqcmggww998jjg0rtzfd6dpufrxy9djk8qyt8wumn8ghj7un9d3shjtnswf5k6ctv9ehx2aqqp3shgar9wd6xzarfdah8xp48yjp)
- [IzzyOnDroid Reproducible Build Logs](https://codeberg.org/IzzyOnDroid/rbtlog)

## License

MIT
