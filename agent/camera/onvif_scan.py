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


def scan(target_ip=None, user=None, passwd=None):
    if user is None and passwd is None:
        user, passwd = _load_credentials()
    if user is None and passwd is None:
        return []
    user = user or ""
    passwd = passwd or ""
    cams = []
    
    ips_to_scan = [target_ip] if target_ip else [f"192.168.0.{i}" for i in range(2, 254)]
    
    import socket
    def fast_check(ip):
        # We check common HTTP/ONVIF ports with a short timeout to prevent 30s hangs
        for port in [80, 8080, 8899, 554]:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.5)
                    if s.connect_ex((ip, port)) == 0:
                        return True
            except Exception:
                pass
        return False

    for ip in ips_to_scan:
        if not fast_check(ip):
            if target_ip:
                print(f"Network device at {ip} did not respond on camera ports.")
            continue
            
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
        except Exception as e:
            print(f"ONVIF error querying {ip}: {e}")
            pass
    return cams
