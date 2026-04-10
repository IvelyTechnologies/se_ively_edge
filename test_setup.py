import sys
import os

from fastapi import Form
from fastapi.testclient import TestClient
from provision_ui.main import app

client = TestClient(app)

response = client.post(
    "/setup",
    data={"ndvr_ip": "192.168.0.195"}
)

print(f"Status Code: {response.status_code}")
if response.status_code == 500:
    print("Internal Server Error detected!")
