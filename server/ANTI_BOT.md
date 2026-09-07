# Server Anti-Bot

The Anti-Bot checks URLs, bare domains, and IP addresses in authenticated
`CHAT` messages before the server distributes them. Messages without an
indicator skip VirusTotal completely.

## Message flow

1. The server parses the incoming protocol message.
2. Only `CHAT` content is passed to `AntiBotService`.
3. The service extracts unique indicators and retrieves existing reputation
   reports from VirusTotal API v3.
4. `MALICIOUS` or `SUSPICIOUS` blocks the whole message and returns an
   `ANTIBOT_BLOCKED` protocol error only to the sender.
5. `CLEAN`, `UNKNOWN`, `LOCAL_PRIVATE`, and `API_ERROR` continue through the
   server's existing message handling.

`UNKNOWN` means VirusTotal has no report. `API_ERROR` means the API key is
missing, VirusTotal timed out, rate-limited the request, or returned an invalid
response. These outcomes allow the message so a VirusTotal outage does not
take down chat; the server logs a warning for the availability/security
tradeoff. Local and private addresses are allowed without an API request.

Successful VirusTotal results are cached in memory for 30 minutes. The cache
key combines indicator type and normalized value. Failures are not cached.
When an exact URL report is missing, the service checks its hostname instead.

## Configuration

Copy `.env.example` to `.env` and replace the placeholder, or set the variable
in the shell:

```powershell
$env:VIRUSTOTAL_API_KEY="your_api_key"
```

Never commit `.env` or a real API key.

## Run and test

From the repository root:

```powershell
pip install -r requirements.txt
python server/server.py
python -m unittest server.test_antibot -v
```

For a demo, send plain text to show that no lookup occurs, send a known clean
URL to show `ANTIBOT_ALLOW`, and use the unit-test fake malicious response to
show a blocked message without calling the real VirusTotal API.
