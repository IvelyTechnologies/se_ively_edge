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
    def get_open_ports(ip):
        open_p = []
        for port in [80, 8899, 8080, 2020, 554]:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.5)
                    if s.connect_ex((ip, port)) == 0:
                        open_p.append(port)
            except Exception:
                pass
        return open_p

    for ip in ips_to_scan:
        open_ports = get_open_ports(ip)
        if not open_ports:
            if target_ip:
                print(f"Network device at {ip} did not respond on camera ports.")
            continue
            
        success = False
        for port in open_ports:
            try:
                cam = ONVIFCamera(ip, port, user, passwd)
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
                print(f"Found {ip} via port {port} with {num_channels} channels")
                success = True
                break
            except Exception as e:
                # Expect false-positives (like web interfaces throwing WSDL/HTTPS parse errors)
                pass
                
        if not success and target_ip:
            print(f"ONVIF query failed on {ip}. Ensure ONVIF is enabled in the device settings.")
    return cams
