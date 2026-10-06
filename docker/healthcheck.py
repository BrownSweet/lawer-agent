"""Check processes and the database-backed setup status through container Nginx."""
import json
import subprocess
import urllib.request


subprocess.run(
    ["/usr/bin/supervisorctl", "-c", "/etc/supervisor/lawer.conf", "status"],
    check=True, stdout=subprocess.DEVNULL,
)
with urllib.request.urlopen("http://127.0.0.1/lawer/api/auth/status", timeout=5) as response:
    if not isinstance(json.load(response).get("initialized"), bool):
        raise SystemExit(1)
