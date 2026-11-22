from grsync_qt.shots import DownloadFormat, group_shots, plan_download


def test_jpg_dng_pair_is_one_shot():
    (shot,) = group_shots(["113RICOH/R0006483.JPG", "113RICOH/R0006483.DNG"])

    assert shot.stem == "R0006483"
    assert set(shot.files) == {"JPG", "DNG"}
    assert shot.key == "113RICOH/R0006483"


def test_unpaired_files_and_video_are_separate_shots():
    shots = group_shots(
        ["100RICOH/R0000002.JPG", "100RICOH/R0000003.MOV", "100RICOH/R0000005.DNG"]
    )

    assert [(s.stem, set(s.files)) for s in shots] == [
        ("R0000005", {"DNG"}),
        ("R0000003", {"MOV"}),
        ("R0000002", {"JPG"}),
    ]
    assert [s.is_video for s in shots] == [False, True, False]


def test_same_base_name_in_different_folders_are_two_shots():
    shots = group_shots(["100RICOH/R0000001.JPG", "101RICOH/R0000001.DNG"])

    assert [s.key for s in shots] == ["101RICOH/R0000001", "100RICOH/R0000001"]


def test_newest_first_across_folders():
    shots = group_shots(
        [
            "112RICOH/R0005797.JPG",
            "112RICOH/R0005798.JPG",
            "113RICOH/R0006483.JPG",
            "113RICOH/R0006484.MOV",
        ]
    )

    assert [s.stem for s in shots] == ["R0006484", "R0006483", "R0005798", "R0005797"]


def test_thumbnail_source_prefers_jpg_then_dng_then_mov():
    pair, dng, mov = group_shots(["1/R3.JPG", "1/R3.DNG", "1/R2.DNG", "1/R1.MOV"])

    assert pair.thumbnail_source == "1/R3.JPG"
    assert pair.other_files == ["1/R3.DNG"]
    assert dng.thumbnail_source == "1/R2.DNG"
    assert mov.thumbnail_source == "1/R1.MOV"


def test_other_extensions_are_ignored():
    assert group_shots(["100RICOH/R0000001.JPG", "100RICOH/INDEX.DAT"])[0].stem == (
        "R0000001"
    )
    assert len(group_shots(["100RICOH/INDEX.DAT"])) == 0


PAIR = ["113RICOH/R0006483.JPG", "113RICOH/R0006483.DNG"]


def test_plan_jpg_raw_of_a_pair():
    plan = plan_download(group_shots(PAIR), DownloadFormat.JPG_RAW)

    assert plan.files == PAIR


def test_plan_raw_only():
    plan = plan_download(group_shots(PAIR), DownloadFormat.RAW)

    assert plan.files == ["113RICOH/R0006483.DNG"]


def test_plan_video_with_jpg_format():
    plan = plan_download(group_shots(["100RICOH/R0000003.MOV"]), DownloadFormat.JPG)

    assert plan.files == ["100RICOH/R0000003.MOV"]


def test_plan_format_not_available():
    plan = plan_download(group_shots(["100RICOH/R0000002.JPG"]), DownloadFormat.RAW)

    assert plan.files == []
    assert plan.shots_not_in_format == ["100RICOH/R0000002"]
