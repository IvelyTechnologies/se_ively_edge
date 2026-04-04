import json
from pathlib import Path

from onvif import ONVIFCamera

from agent.security.vault import decrypt

VAULT_PATH = Path("/opt/ively/agent/camera.vault")


def _load_credentials():
    """Load vault credentials. Returns (user, pass) or (None, None) if vault missing."""
    if not VAULT_PATH.exists():
        return None, None
    try:
        with open(VAULT_PATH, encoding="utf-8") as f:
            vault = json.load(f)
        return decrypt(vault["user"]), decrypt(vault["password"])
    except Exception:
        return None, None


def scan():
    user, passwd = _load_credentials()
    if user is None and passwd is None:
        return []
    user = user or ""
    passwd = passwd or ""
    cams = []
    for i in range(2, 254):
        ip = f"192.168.0.{i}"
        try:
            cam = ONVIFCamera(ip, 80, user, passwd)
            info = cam.devicemgmt.GetDeviceInformation()
            
            num_channels = 1
            try:
                media = cam.create_media_service()
                video_sources = media.GetVideoSources()
                if video_sources and len(video_sources) > 0:
                    num_channels = len(video_sources)
            except Exception:
                pass
                
            cams.append({"ip": ip, "model": info.Model, "channels": num_channels})
            print(f"Found {ip} with {num_channels} channels")
        except Exception:
            pass
    return cams
