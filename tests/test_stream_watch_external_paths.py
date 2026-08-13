from agent.camera.stream_watch import is_external_publisher_path, load_stream_paths


def test_external_analog_paths_are_excluded_from_nvr_recovery(tmp_path):
    config = tmp_path / "mediamtx.yml"
    config.write_text(
        """paths:
  customer_cam1_low:
    source: publisher
  customer_analog_dvr_ch1_low:
    source: publisher
""",
        encoding="utf-8",
    )

    assert load_stream_paths(str(config), include_external=False) == ["customer_cam1_low"]
    assert is_external_publisher_path("customer_analog_dvr_ch1_low") is True
    assert is_external_publisher_path("customer_cam1_low") is False
