from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse
import subprocess

app = FastAPI()

MANUFACTURERS = [
    ("auto", "Auto-detect from camera"),
    ("hikvision", "Hikvision"),
    ("dahua", "Dahua"),
    ("cp plus", "CP Plus"),
    ("godrej", "Godrej"),
    ("prama", "Prama"),
    ("axis", "Axis"),
    ("bosch", "Bosch"),
    ("hanwha", "Hanwha (Samsung Techwin)"),
    ("zicom", "Zicom"),
    ("tp-link", "TP-Link"),
    ("ezviz", "Ezviz"),
    ("imou", "Imou"),
    ("reolink", "Reolink"),
    ("panasonic", "Panasonic"),
    ("sony", "Sony"),
    ("samsung", "Samsung"),
    ("pelco", "Pelco"),
    ("avigilon", "Avigilon"),
    ("mobotix", "Mobotix"),
    ("secureye", "Secureye"),
    ("uniview", "Uniview"),
    ("tiandy", "Tiandy"),
    ("onvif", "ONVIF (generic)"),
]


@app.get("/", response_class=HTMLResponse)
def page():
    options = "".join(
        f'<option value="{v}">{label}</option>' for v, label in MANUFACTURERS
    )
    return f"""
    <h2>Ively SmartEye™ Setup</h2>
    <form method='post' action='/setup'>
      Cloud URL: <input name='cloud_url' placeholder='cloud.ively.ai' value='cloud.ively.ai' required><br>
      Customer name: <input name='customer' placeholder='e.g. Acme Corp' required><br>
      Site name: <input name='site' placeholder='e.g. Warehouse A' required><br>
      Camera manufacturer: <select name='manufacturer'>{options}</select><br>
      Camera Username: <input name='user'><br>
      Camera Password: <input name='pwd' type='password'><br>
      <button>Start Setup</button>
    </form>
    """


@app.post("/setup")
def setup(
    user: str = Form(...),
    pwd: str = Form(...),
    manufacturer: str = Form("auto"),
    customer: str = Form(""),
    site: str = Form(""),
    cloud_url: str = Form("cloud.ively.ai"),
):
    subprocess.Popen([
        "python3",
        "/opt/ively/edge/installer/provision_device.py",
        user,
        pwd,
        manufacturer,
        customer.strip() or "customer",
        site.strip() or "site",
        cloud_url.strip() or "cloud.ively.ai",
    ])
    return {"status": "Provisioning started"}
