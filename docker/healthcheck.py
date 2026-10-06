"""Check all processes and an authenticated database probe through container Nginx."""
import json
import subprocess
import urllib.request

from law_backend.api import session_identity, signer

subprocess.run(
    ["/usr/bin/supervisorctl", "-c", "/etc/supervisor/lawer.conf", "status"],
    check=True, stdout=subprocess.DEVNULL,
)
request = urllib.request.Request(
    "http://127.0.0.1/lawer/api/health",
    headers={"Cookie": f"law_session={signer.dumps(session_identity)}"},
)
with urllib.request.urlopen(request, timeout=5) as response:
    if not json.load(response).get("ok"):
        raise SystemExit(1)
