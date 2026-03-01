# camera discovery

from agent.camera.onvif_scan import scan
from agent.camera.mediamtx_writer import generate


def run():
    cams = scan()
    generate(cams)
    print("Configured", len(cams), "cameras")


if __name__ == "__main__":
    run()
