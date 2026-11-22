"""Group the camera's files into shots and plan which files to download."""

from dataclasses import dataclass, field
from enum import Enum

JPG = "JPG"
DNG = "DNG"
MOV = "MOV"
STILL_EXTENSIONS = (JPG, DNG)


@dataclass(frozen=True)
class Shot:
    """One picture or video: a JPG and/or DNG with the same name, or a MOV.

    files maps the upper-case extension to the file's 'dir/name' path.
    """

    dir: str
    stem: str
    files: dict[str, str] = field(hash=False)

    @property
    def key(self) -> str:
        """Stable identity across refreshes: 'dir/stem' ('dir/name' for videos)."""
        if self.is_video:
            return self.files[MOV]
        return f"{self.dir}/{self.stem}"

    @property
    def is_video(self) -> bool:
        return MOV in self.files

    @property
    def thumbnail_source(self) -> str:
        """The file whose thumbnail represents the shot: JPG, else DNG, else MOV."""
        for extension in (JPG, DNG, MOV):
            if extension in self.files:
                return self.files[extension]
        raise ValueError(f"shot {self.key} has no files")

    @property
    def other_files(self) -> list[str]:
        """The shot's files besides the thumbnail source."""
        return [path for path in self.files.values() if path != self.thumbnail_source]


def split_path(path: str) -> tuple[str, str, str]:
    """Split 'dir/R0000001.JPG' into ('dir', 'R0000001', 'JPG')."""
    dir_name, file_name = path.split("/", 1)
    stem, _, extension = file_name.rpartition(".")
    return dir_name, stem, extension.upper()


def group_shots(paths: list[str]) -> list[Shot]:
    """Group listing paths into shots, newest first.

    Files with other extensions than JPG, DNG and MOV are left out.
    """
    stills: dict[tuple[str, str], dict[str, str]] = {}
    videos: list[Shot] = []
    for path in paths:
        dir_name, stem, extension = split_path(path)
        if extension == MOV:
            videos.append(Shot(dir_name, stem, {MOV: path}))
        elif extension in STILL_EXTENSIONS:
            stills.setdefault((dir_name, stem), {})[extension] = path
    shots = [Shot(d, s, files) for (d, s), files in stills.items()] + videos
    # Folder and file numbers grow with every shot, so this is newest first.
    return sorted(shots, key=lambda shot: (shot.dir, shot.stem), reverse=True)


class DownloadFormat(Enum):
    JPG = "JPG"
    RAW = "RAW"
    JPG_RAW = "JPG+RAW"


FORMAT_EXTENSIONS = {
    DownloadFormat.JPG: (JPG,),
    DownloadFormat.RAW: (DNG,),
    DownloadFormat.JPG_RAW: (JPG, DNG),
}


@dataclass
class DownloadPlan:
    """The files to download, and the shots without a file in the format."""

    files: list[str]
    shots_not_in_format: list[str]


def files_to_download(shot: Shot, download_format: DownloadFormat) -> list[str]:
    """Return the shot's files in the chosen format; videos always as MOV."""
    if shot.is_video:
        return [shot.files[MOV]]
    extensions = FORMAT_EXTENSIONS[download_format]
    return [shot.files[ext] for ext in extensions if ext in shot.files]


def plan_download(shots: list[Shot], download_format: DownloadFormat) -> DownloadPlan:
    """Build the download plan for shots, keeping their order."""
    plan = DownloadPlan(files=[], shots_not_in_format=[])
    for shot in shots:
        files = files_to_download(shot, download_format)
        if not files:
            plan.shots_not_in_format.append(shot.key)
        plan.files.extend(files)
    return plan
