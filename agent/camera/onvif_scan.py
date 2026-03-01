import json

from onvif import ONVIFCamera

from agent.security.vault import decrypt

with open("/opt/ively/agent/camera.vault") as f:
    vault = json.load(f)

USER = decrypt(vault["user"])
PASS = decrypt(vault["password"])


def scan():
    cams = []
    for i in range(2, 254):
        ip = f"192.168.1.{i}"
        try:
            cam = ONVIFCamera(ip, 80, USER, PASS)
            info = cam.devicemgmt.GetDeviceInformation()
            cams.append({"ip": ip, "model": info.Model})
            print("Found", ip)
        except Exception:
            pass
    return cams
