"""The fake camera must behave like the measured GR III, or the tests lie."""

import threading

import pytest
import requests
from fake_camera import FakeCamera, FakeFile, file_content
from PySide6.QtGui import QImage


def get(camera: FakeCamera, path: str, **kwargs) -> requests.Response:
    return requests.get(camera.url + path, timeout=5, **kwargs)


def decode(body: bytes) -> QImage:
    image = QImage()
    assert image.loadFromData(body)
    return image


def test_props_and_listing(fake_camera):
    props = get(fake_camera, "v1/props").json()
    listing = get(fake_camera, "v1/photos").json()

    assert props["model"] == "RICOH GR III"
    assert [d["name"] for d in listing["dirs"]] == ["100RICOH", "101RICOH"]
    assert listing["dirs"][0]["files"][:2] == ["R0000001.JPG", "R0000001.DNG"]


def test_info_fields(fake_camera):
    info = get(fake_camera, "v1/photos/101RICOH/R0000006.JPG/info").json()

    assert info["size"] == fake_camera.file("101RICOH/R0000006.JPG").size
    assert info["orientation"] == 6
    assert info["datetime"] == "2026-11-22T12:00:00"


def test_head_returns_404(fake_camera):
    response = requests.head(fake_camera.url + "v1/photos/100RICOH/R0000001.JPG")

    assert response.status_code == 404
    assert response.headers["Content-Length"] == "15"


def test_range_is_ignored(fake_camera):
    path = "v1/photos/100RICOH/R0000001.DNG"
    response = get(fake_camera, path, headers={"Range": "bytes=0-0"})

    assert response.status_code == 200
    assert response.content == file_content(fake_camera.file("100RICOH/R0000001.DNG"))


def test_jpg_thumb_is_letterboxed_160x120(fake_camera):
    image = decode(
        get(fake_camera, "v1/photos/100RICOH/R0000001.JPG?size=thumb").content
    )

    assert (image.width(), image.height()) == (160, 120)
    assert max(image.pixelColor(80, 2).getRgb()[:3]) < 24
    assert max(image.pixelColor(80, 60).getRgb()[:3]) > 24


@pytest.mark.parametrize(
    ("path", "size"),
    [("100RICOH/R0000001.DNG", (720, 480)), ("100RICOH/R0000003.MOV", (640, 360))],
)
def test_dng_and_mov_thumb_equal_view(fake_camera, path, size):
    thumb = get(fake_camera, f"v1/photos/{path}?size=thumb").content
    view = get(fake_camera, f"v1/photos/{path}?size=view").content

    assert thumb == view
    image = decode(view)
    assert (image.width(), image.height()) == size


def test_image_and_file_responses_forbid_caching(fake_camera):
    thumb = get(fake_camera, "v1/photos/100RICOH/R0000001.JPG?size=thumb")
    full = get(fake_camera, "v1/photos/100RICOH/R0000001.JPG")

    assert thumb.headers["Cache-Control"] == "no-store, no-cache"
    assert full.headers["Cache-Control"] == "no-store, no-cache"
    assert int(full.headers["Content-Length"]) == len(full.content)


def test_unknown_file_is_404(fake_camera):
    assert get(fake_camera, "v1/photos/100RICOH/R9999999.JPG").status_code == 404


def test_error_switch(fake_camera):
    fake_camera.errors["/v1/photos/100RICOH/R0000001.JPG"] = 500

    assert get(fake_camera, "v1/photos/100RICOH/R0000001.JPG").status_code == 500
    assert get(fake_camera, "v1/photos/100RICOH/R0000001.JPG/info").status_code == 200


def test_drop_switch_cuts_the_body(fake_camera):
    fake_camera.drops.add("/v1/photos/100RICOH/R0000001.DNG")

    with pytest.raises(requests.exceptions.ChunkedEncodingError):
        get(fake_camera, "v1/photos/100RICOH/R0000001.DNG")


def test_delay_switch(fake_camera):
    fake_camera.delay = 0.2

    response = get(fake_camera, "v1/props")

    assert response.elapsed.total_seconds() >= 0.2


def test_gone_switch(fake_camera):
    fake_camera.gone = True

    with pytest.raises(requests.exceptions.ConnectionError):
        get(fake_camera, "v1/props")


def test_props_raw_switch(fake_camera):
    fake_camera.props_raw = b"<html>router</html>"

    assert get(fake_camera, "v1/props").text == "<html>router</html>"


def test_request_log_records_method_path_and_concurrency(fake_camera):
    fake_camera.delay = 0.2
    threads = [
        threading.Thread(target=get, args=(fake_camera, "v1/props")) for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    requests.post(fake_camera.url + "v1/device/finish", timeout=5)

    assert fake_camera.paths_requested("GET") == ["/v1/props", "/v1/props"]
    assert fake_camera.paths_requested("POST") == ["/v1/device/finish"]
    assert fake_camera.max_concurrent == 2


def test_card_is_configurable():
    camera = FakeCamera(card=[FakeFile("120RICOH", "R0000009.JPG", size=1234)]).start()
    try:
        listing = get(camera, "v1/photos").json()
        full = get(camera, "v1/photos/120RICOH/R0000009.JPG")
    finally:
        camera.stop()

    assert listing["dirs"] == [{"name": "120RICOH", "files": ["R0000009.JPG"]}]
    assert len(full.content) == 1234
