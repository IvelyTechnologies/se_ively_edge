import sys
sys.path.insert(0, './provision-ui')
import threading
import time
import requests
import uvicorn
from main import app

def run_server():
    uvicorn.run(app, host="127.0.0.1", port=2029, log_level="error")

t = threading.Thread(target=run_server, daemon=True)
t.start()

time.sleep(2) # wait for server

try:
    resp = requests.post("http://127.0.0.1:2029/setup", data={"ndvr_ip": "192.168.0.195", "user": "", "pwd": "", "manufacturer": "auto", "customer": "test", "site": "test", "cloud_url": "test.ai"})
    print("Status:", resp.status_code)
    print(resp.text[:200])
except Exception as e:
    print("Error:", e)
