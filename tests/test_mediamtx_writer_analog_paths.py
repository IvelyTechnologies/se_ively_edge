from agent.camera.mediamtx_writer import _load_analog_dvr_publisher_paths


def test_load_analog_dvr_paths_from_existing_mediamtx_config(tmp_path):
    config = tmp_path / "mediamtx.yml"
    config.write_text(
        """rtsp: yes
paths:
  customer_nvr_cam1_low:
    source: publisher
  loshitha_analog_dvr_ch1_low:
    source: publisher
  loshitha_analog_dvr_ch5_low:
    source: publisher
api: yes
""",
        encoding="utf-8",
    )

    assert _load_analog_dvr_publisher_paths(str(config)) == [
        "loshitha_analog_dvr_ch1_low",
        "loshitha_analog_dvr_ch5_low",
    ]
