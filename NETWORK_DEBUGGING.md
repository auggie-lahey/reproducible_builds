# GitHub Actions Network Restrictions Investigation

## Hypothesis: GitHub Actions blocks WebSocket responses

### Evidence:
1. nak connects successfully (stderr shows "connecting... ok")
2. But receives 0 bytes of event data
3. Happens across ALL relays (not just one)

### Possible Causes:

#### 1. GitHub Actions Network Filtering
- GitHub Actions may block WebSocket data frames for security
- Allow WebSocket handshake but block message content
- This would explain "connecting... ok" but no data

#### 2. Relay-side IP Filtering
- Relays may blacklist known GitHub Actions IP ranges
- They might complete handshake but send no events
- This is common for anti-abuse measures

#### 3. WebSocket Protocol Issues
- GitHub Actions' network might not support WebSocket frames properly
- Only allows TCP/HTTP but not WebSocket message frames

### Testing Strategy:

1. **Try raw WebSocket with wscat** - See if any WebSocket messages get through
2. **Check HTTP endpoints** - See if regular HTTP works fine
3. **Test from self-hosted runner** - If it works there, it's GitHub's network
4. **Use a VPN/tunnel** - Route around potential GitHub blocking

### Workarounds:

1. **Use self-hosted GitHub Actions runner**
   - Run on your own infrastructure
   - Full network control

2. **Use a VPN/proxy service in workflow**
   - Tunnel traffic through residential IP
   - Bypass GitHub's network filtering

3. **Use alternative relay discovery**
   - Don't query relays from GitHub Actions
   - Use pre-configured relay lists
   - Query relays from local machine

4. **HTTP-based relay APIs**
   - Some relays offer HTTP REST APIs
   - Bypass WebSocket entirely

### Resources:
- GitHub Actions network docs: https://docs.github.com/en/actions/security-guides hardening-github-actions
- Known IP ranges: https://api.github.com/meta
- WebSocket issues: https://github.com/actions/runner/issues
