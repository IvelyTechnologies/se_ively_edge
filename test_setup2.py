import sys
sys.path.insert(0, './provision-ui')

from main import setup_step1_discover

try:
    html = setup_step1_discover(ndvr_ip="192.168.0.195", user="", pwd="", manufacturer="auto", customer="", site="", cloud_url="cloud.ively.ai", customer_id="", site_id="")
    print("SUCCESS")
except Exception as e:
    import traceback
    traceback.print_exc()
