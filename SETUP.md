# Setup Guide

## Prerequisites

1. **Python 3.9+**
   ```bash
   python --version
   ```

2. **nak CLI** (Nostr command-line tool)
   ```bash
   # Install from GitHub releases
   curl -LO https://github.com/0xtrm/nak/releases/download/v0.3.0/nak_0.3.0_linux_amd64.tar.gz
   tar xzf nak_0.3.0_linux_amd64.tar.gz
   chmod +x nak
   sudo mv nak /usr/local/bin/
   
   # Verify installation
   nak --version
   ```

3. **Git** (for GitHub Actions)
   ```bash
   git --version
   ```

## Installation

### 1. Clone the Repository

```bash
git clone <your-repo-url>
cd reproducible_builds
```

### 2. Install Python Dependencies

```bash
# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Generate Nostr Keys

```bash
# Generate a new key pair
nak key gen

# Save the output - you'll get something like:
# nsec1... (private key - keep this secret!)
# npub1... (public key - this is your identity)
```

### 4. Configure the System

Edit `config.yaml`:

```yaml
nostr:
  # Add your nsec here (NEVER commit this to git!)
  nsec: "nsec1your-private-key-here"
  relays:
    - "wss://relay.damus.io"
    - "wss://relay.primal.net"

apps:
  org.fossify.calendar:
    izzy_appid: "org.fossify.calendar"
    zapstore_appid: "calendar"
    izzy_log_file: "org.fossify.calendar.json"
    arch: "armeabi-v7a"
    commit_template: "v{version}"
```

## Usage

### Local Testing

Test with a dry run (events are echoed but not published):

```bash
# Check a specific app
python scripts/check_reproducible.py --app org.fossify.calendar --dry-run

# Check all configured apps
python scripts/check_reproducible.py --dry-run
```

### Publish for Real

```bash
# Publish events (this will create actual Nostr events!)
python scripts/check_reproducible.py --app org.fossify.calendar
```

### Manual Event Creation

You can also create events manually using `nak`:

```bash
# Example: Publish a test event
nak event publish \
  nsec1your-key \
  --kind 1 \
  --content "Test event from reproducible build checker"
```

## GitHub Actions Setup

### 1. Fork/Create Repository

Push this code to your GitHub repository.

### 2. Configure Secrets

Go to: **Settings → Secrets and variables → Actions → New repository secret**

Add the following secret:

- **Name**: `NSEC`
- **Value**: Your nsec private key (e.g., `nsec1...`)

### 3. Enable Actions

1. Go to the **Actions** tab
2. Click on **"Reproducible Build Checker"**
3. Click **"Enable workflow"** if needed

### 4. Run Workflow

**Scheduled Runs:**
- Runs automatically daily at 2 AM UTC

**Manual Run:**
1. Go to **Actions** tab
2. Select **"Reproducible Build Checker"**
3. Click **"Run workflow"**
4. Optionally specify:
   - App ID (to check a specific app)
   - Dry run (to test without publishing)

### 5. Monitor Results

- Check the **Actions** tab for workflow runs
- View logs to see what was published
- Events are echoed before publishing for review

## Understanding the Output

### State File

After each run, `state.json` is updated with checked versions:

```json
{
  "org.fossify.calendar": {
    "1.0.3": {
      "checked": true,
      "event_id": "abc123..."
    },
    "1.1.0": {
      "checked": true,
      "event_id": "def456..."
    }
  }
}
```

### Nostr Events

For each new version, two events are created:

1. **Assertion Event** (kind 1063)
   - Declares reproducibility status
   - Contains SHA256 hash, version, commit reference

2. **Attestation Event** (kind 1063)
   - References the assertion event
   - Confirms the assertion is true

## Troubleshooting

### "No nsec configured"
- Add your nsec to `config.yaml`
- For GitHub Actions, add it as a repository secret

### "Failed to fetch log"
- Check internet connection
- Verify app ID matches Izzy's log file name
- Check Codeberg API status

### "Failed to publish event"
- Verify nsec is correct
- Check relay URLs are accessible
- Try with `--dry-run` first to see the event content

### "No new versions"
- This is normal if all versions are already checked
- Check `state.json` to see what's been processed
- To re-check, remove versions from `state.json`

## Next Steps

1. **Add More Apps**
   - Edit `config.yaml` to add more apps
   - Map zapstore IDs to Izzy app IDs

2. **Customize Event Templates**
   - Edit `templates/assertion.json`
   - Edit `templates/attestation.json`

3. **Set Up Monitoring**
   - Create a dashboard to view attestations
   - Subscribe to your Nostr events

4. **Integration**
   - Connect with zapstore frontend
   - Create bots to respond to events

## Security Notes

- **NEVER commit your nsec to git**
- Use GitHub Secrets for keys in Actions
- Keep your nsec safe - it's your private key
- Consider using a dedicated key for this system

## Resources

- [Zapstore Issue #23](https://github.com/zapstore/zapstore/issues/23)
- [IzzyOnDroid Reproducible Builds](https://codeberg.org/IzzyOnDroid/rbtlog)
- [Nostr NIPs](https://github.com/nostr-protocol/nips)
- [nak CLI](https://github.com/0xtrm/nak)
