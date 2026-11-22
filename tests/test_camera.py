import logging
import socket
import time

import pytest
from fake_camera import SECRET_PROPS, file_content

from grsync_qt.camera import (
    CONNECT_TIMEOUT_SECONDS,
    CameraClient,
    CameraHttpError,
    CameraInfo,
    CameraUnreachable,
    DownloadCancelled,
    UnsupportedCamera,
)

DNG_PATH = "100RICOH/R0000001.DNG"


@pytest.fixture
def client(fake_camera):
    return CameraClient(fake_camera.url)


def closed_port_url() -> str:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}/"


def test_gr_iii_connects(client):
    info = client.props()

    assert info == CameraInfo(model="RICOH GR III", battery=87, firmware="1.20")


def test_gr_iiix_connects(fake_camera, client):
    fake_camera.props["model"] = "RICOH GR IIIx"

    assert client.props().model == "RICOH GR IIIx"


def test_gr_ii_is_rejected_naming_the_model(fake_camera, client):
    fake_camera.props["model"] = "RICOH GR II"

    with pytest.raises(UnsupportedCamera, match="RICOH GR II") as error:
        client.props()
    assert error.value.model == "RICOH GR II"


def test_non_json_page_is_rejected(fake_camera, client):
    fake_camera.props_raw = b"<html>router login</html>"

    with pytest.raises(UnsupportedCamera, match="no camera model") as error:
        client.props()
    assert error.value.model is None


def test_closed_port_is_unreachable_within_connect_timeout():
    client = CameraClient(closed_port_url())
    started = time.monotonic()

    with pytest.raises(CameraUnreachable, match="not reachable"):
        client.props()
    assert time.monotonic() - started < CONNECT_TIMEOUT_SECONDS + 1


def test_http_error_status(fake_camera, client):
    fake_camera.errors["/v1/photos/100RICOH/R0000001.JPG/info"] = 500

    with pytest.raises(CameraHttpError) as error:
        client.info("100RICOH/R0000001.JPG")
    assert error.value.status == 500


def test_listing_file_names(client):
    assert client.listing()[:3] == [
        "100RICOH/R0000001.JPG",
        "100RICOH/R0000001.DNG",
        "100RICOH/R0000002.JPG",
    ]


def test_info_fields(fake_camera, client):
    info = client.info("101RICOH/R0000006.JPG")

    assert info.size == fake_camera.file("101RICOH/R0000006.JPG").size
    assert info.orientation == 6
    assert info.datetime == "2026-11-22T12:00:00"


def test_image_bytes(client):
    assert client.image("100RICOH/R0000001.JPG", "thumb")[:2] == b"\xff\xd8"


def test_download_byte_count_equals_content_length(fake_camera, client):
    chunks = []

    result = client.download(DNG_PATH, chunks.append, lambda: False)

    assert result.received_size == result.announced_size == 600 * 1024
    assert b"".join(chunks) == file_content(fake_camera.file(DNG_PATH))


def test_cancel_stops_within_one_chunk(client):
    chunks = []

    with pytest.raises(DownloadCancelled):
        client.download(DNG_PATH, chunks.append, lambda: len(chunks) >= 1)
    assert len(chunks) == 1


def test_dropped_connection_raises_unreachable(fake_camera, client):
    fake_camera.drops.add("/v1/photos/" + DNG_PATH)

    with pytest.raises(CameraUnreachable, match="Connection lost"):
        client.download(DNG_PATH, lambda chunk: None, lambda: False)


def test_camera_gone_raises_unreachable(fake_camera, client):
    fake_camera.gone = True

    with pytest.raises(CameraUnreachable):
        client.listing()


def test_only_get_requests_are_sent(fake_camera, client):
    client.props()
    client.listing()
    client.info("100RICOH/R0000001.JPG")
    client.image("100RICOH/R0000001.JPG", "view")
    client.download(DNG_PATH, lambda chunk: None, lambda: False)

    assert {entry.method for entry in fake_camera.log} == {"GET"}


def test_secrets_stay_out_of_logs_and_camera_info(client, caplog):
    caplog.set_level(logging.DEBUG)

    info = client.props()
    client.listing()

    for secret in SECRET_PROPS.values():
        assert secret not in caplog.text
        assert secret not in repr(info)
    assert "GET" in caplog.text


def test_info_exposure_fields(client):
    info = client.info("101RICOH/R0000006.JPG")

    assert (info.aperture, info.shutter_speed, info.iso) == ("4.5", "1.4", "3200")
    assert info.exposure_compensation == "0.0"


def test_info_leaves_out_the_shots_gps_position(client):
    info = client.info("101RICOH/R0000006.JPG")

    assert "GPS" not in repr(info)
