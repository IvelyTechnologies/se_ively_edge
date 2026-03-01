# WebSocket command handler — dispatch cloud commands (OTA, etc.)

import json

try:
    from agent.ota.updater import update as ota_update
except ImportError:
    ota_update = None


def handle(msg: str) -> str | None:
    """
    Parse JSON command and run the right handler. Returns optional response text.
    """
    try:
        cmd = json.loads(msg)
    except json.JSONDecodeError:
        return None

    action = (cmd.get("action") or "").strip()
    if not action:
        return None

    if action == "ota_update":
        if ota_update is None:
            return json.dumps({"success": False, "message": "OTA module not available"})
        repo = cmd.get("repo") or ""
        version = cmd.get("version") or ""
        result = ota_update(repo, version)
        return json.dumps(result)

    return None
