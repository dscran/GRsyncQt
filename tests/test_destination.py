import os

from grsync_qt.destination import (
    DestinationIndex,
    create_temp_file,
    finalize,
    is_writable,
    remove_leftover_temp_files,
)


def write(folder, name, size):
    (folder / name).write_bytes(b"x" * size)


def test_same_name_and_size_is_present(tmp_path):
    write(tmp_path, "R0006483.JPG", 100)

    index = DestinationIndex(tmp_path)

    assert index.has_name_match("R0006483.JPG")
    assert index.is_present("R0006483.JPG", 100)
    assert not index.is_present("R0006483.JPG", 99)


def test_name_comparison_ignores_case(tmp_path):
    write(tmp_path, "r0006483.jpg", 100)

    assert DestinationIndex(tmp_path).is_present("R0006483.JPG", 100)


def test_present_under_a_collision_name(tmp_path):
    write(tmp_path, "R0000001.JPG", 50)
    write(tmp_path, "R0000001_2.JPG", 100)

    assert DestinationIndex(tmp_path).is_present("R0000001.JPG", 100)


def test_underscore_one_is_not_a_collision_name(tmp_path):
    write(tmp_path, "R0000001_1.JPG", 100)

    index = DestinationIndex(tmp_path)

    assert not index.has_name_match("R0000001.JPG")


def test_other_extension_is_no_name_match(tmp_path):
    write(tmp_path, "R0000001.DNG", 100)

    assert not DestinationIndex(tmp_path).has_name_match("R0000001.JPG")


def test_free_name_is_the_camera_name(tmp_path):
    assert DestinationIndex(tmp_path).target_name("R0000001.JPG") == "R0000001.JPG"


def test_counter_wrap_gives_underscore_2(tmp_path):
    write(tmp_path, "R0000001.JPG", 50)

    assert DestinationIndex(tmp_path).target_name("R0000001.JPG") == "R0000001_2.JPG"


def test_existing_file_is_never_the_target(tmp_path):
    for name in ("R0000001.JPG", "R0000001_2.JPG", "r0000001_3.jpg"):
        write(tmp_path, name, 50)

    target = DestinationIndex(tmp_path).target_name("R0000001.JPG")

    assert target == "R0000001_4.JPG"
    assert not (tmp_path / target).exists()


def test_missing_folder_is_empty(tmp_path):
    index = DestinationIndex(tmp_path / "missing")

    assert not index.has_name_match("R0000001.JPG")


def test_temp_files_are_not_indexed(tmp_path):
    temp_path = create_temp_file(tmp_path)

    assert temp_path.name.startswith(".grsync-qt-")
    assert temp_path.name.endswith(".part")
    assert DestinationIndex(tmp_path).target_name(temp_path.name) == temp_path.name


def test_leftovers_are_removed_while_other_files_stay(tmp_path):
    leftover = create_temp_file(tmp_path)
    write(tmp_path, "R0000001.JPG", 10)
    write(tmp_path, "notes.part", 10)

    remove_leftover_temp_files(tmp_path)

    assert not leftover.exists()
    assert sorted(os.listdir(tmp_path)) == ["R0000001.JPG", "notes.part"]


def test_finalize_moves_the_temp_file_to_the_camera_name(tmp_path):
    temp_path = create_temp_file(tmp_path)
    temp_path.write_bytes(b"new")

    target = finalize(temp_path, "R0000001.JPG")

    assert target == tmp_path / "R0000001.JPG"
    assert target.read_bytes() == b"new"
    assert not temp_path.exists()


def test_finalize_does_not_overwrite_a_file_created_meanwhile(tmp_path):
    index = DestinationIndex(tmp_path)
    temp_path = create_temp_file(tmp_path)
    temp_path.write_bytes(b"new")
    write(tmp_path, index.target_name("R0000001.JPG"), 5)  # appears meanwhile

    target = finalize(temp_path, "R0000001.JPG")

    assert target.name == "R0000001_2.JPG"
    assert (tmp_path / "R0000001.JPG").read_bytes() == b"xxxxx"


def test_writable_check(tmp_path):
    read_only = tmp_path / "read-only"
    read_only.mkdir()
    read_only.chmod(0o500)
    try:
        assert is_writable(tmp_path)
        assert not is_writable(read_only)
        assert not is_writable(tmp_path / "missing")
    finally:
        read_only.chmod(0o700)
    assert os.listdir(tmp_path) == ["read-only"]
