# photo-download Specification

## Purpose

Lets the user copy selected shots from the camera to one local folder as JPG,
RAW or both, safely and without duplicates, while seeing progress and keeping
control over the transfer.

## Requirements

### Requirement: Destination folder
The user SHALL choose the destination folder. The app SHALL remember it across
sessions, and SHALL ask for it when a download starts and none is set or the
remembered folder no longer exists.

#### Scenario: First download
- **WHEN** the user starts the first download and no destination is set
- **THEN** the app asks for a folder and downloads into it after the user picks one

#### Scenario: Remembered folder
- **WHEN** the user restarts the app
- **THEN** the destination chosen in the previous session is still selected

#### Scenario: Folder not writable
- **WHEN** the chosen folder cannot be written to
- **THEN** the app says so before downloading anything and lets the user pick another folder

### Requirement: Format choice
The user SHALL choose to download JPG, RAW (DNG) or JPG+RAW. The choice SHALL
apply to every selected still shot and SHALL be remembered across sessions.
Videos SHALL always be downloaded as MOV.

#### Scenario: JPG+RAW of a pair
- **WHEN** a JPG+DNG shot is selected and the format is JPG+RAW
- **THEN** both files are downloaded

#### Scenario: RAW only
- **WHEN** a JPG+DNG shot is selected and the format is RAW
- **THEN** only the DNG is downloaded

#### Scenario: Video in the selection
- **WHEN** a video shot is selected and the format is JPG
- **THEN** the MOV is downloaded

#### Scenario: Format not available for a shot
- **WHEN** the format is RAW and a selected shot has only a JPG
- **THEN** nothing is downloaded for that shot, and the summary counts it as having no file in the chosen format

### Requirement: Flat folder with camera file names
Downloaded files SHALL be saved directly in the destination folder, without
subfolders, under the camera's file name.

#### Scenario: File placement
- **WHEN** `113RICOH/R0006483.DNG` is downloaded to `~/Pictures/GR`
- **THEN** it is saved as `~/Pictures/GR/R0006483.DNG`

### Requirement: Already present files skipped
A file SHALL NOT be downloaded when the destination folder already holds a file
with the same size under its name, or under a collision name of it (see the
requirement below). Such files SHALL be counted as already present.

#### Scenario: Same name and size
- **WHEN** `R0006483.JPG` (10285531 bytes on the camera) is selected and `R0006483.JPG` of 10285531 bytes is in the destination
- **THEN** it is not downloaded and is counted as already present

#### Scenario: Present under a collision name
- **WHEN** the destination holds `R0000001.JPG` of another size and `R0000001_2.JPG` with the camera file's size
- **THEN** the camera file is not downloaded and is counted as already present

### Requirement: Existing files never overwritten
When the destination holds a different file (other size) under the camera
file's name, the download SHALL be saved as `<name>_<n>.<ext>`, using the
lowest `n` from 2 up that is free. No existing file SHALL ever be overwritten.

#### Scenario: Counter wrapped around
- **WHEN** `R0000001.JPG` exists locally with another size than the camera's `R0000001.JPG`
- **THEN** the camera file is saved as `R0000001_2.JPG` and the existing file is unchanged

### Requirement: Only complete files kept
A file SHALL appear under its final name only after all its bytes have arrived
and their count matches the size the camera announced. An incomplete or
mismatched transfer SHALL leave no file behind and SHALL be reported as failed.

#### Scenario: Interrupted transfer
- **WHEN** the connection drops halfway through a DNG
- **THEN** no file with that DNG's name (or any partial file) remains in the destination, and the file is reported as failed

#### Scenario: Size mismatch
- **WHEN** fewer bytes arrive than the camera announced
- **THEN** the file is discarded and reported as failed

### Requirement: One file at a time
Downloads SHALL run one file at a time, in the grid's order, while the user
keeps browsing. Thumbnails and previews SHALL keep loading during a download.

#### Scenario: Browsing during a download
- **WHEN** a download is running and the user scrolls to shots without thumbnails
- **THEN** their thumbnails load while the download continues

### Requirement: Progress shown
During a download the app SHALL show the current file, its position in the
queue (file N of M), the overall progress in bytes, the transfer speed and an
estimated time remaining.

#### Scenario: Progress update
- **WHEN** the third of ten files is downloading
- **THEN** the window shows its file name, "3 of 10", overall progress, speed and time remaining, updated at least once per second

### Requirement: Cancel
The user SHALL be able to cancel a running download. Cancelling SHALL stop the
current file without leaving it behind. Files finished before the cancel SHALL
be kept, and no further files SHALL be downloaded.

#### Scenario: Cancel mid-file
- **WHEN** the user cancels while the fifth of ten files is half transferred
- **THEN** files one to four remain in the destination, the fifth leaves nothing behind, and files six to ten are not downloaded

### Requirement: Failures reported
A file that fails because of a camera error, timeout, size mismatch or local
write error SHALL be reported with its reason, and the remaining files SHALL
continue. When the camera stops answering, the remaining files SHALL NOT be
attempted, and the app SHALL show the connection loss.

#### Scenario: One file fails
- **WHEN** the camera answers one file with an error status
- **THEN** that file is reported as failed with the status, and the next file starts

#### Scenario: Camera gone
- **WHEN** the camera stops answering during a download
- **THEN** the current file is reported as failed, the remaining files are listed as not attempted, and the app shows it is disconnected

### Requirement: Download summary
After a download ends (finished, cancelled or stopped), the app SHALL show how
many files were downloaded, already present, unavailable in the chosen format,
failed (with reasons) and not attempted.

#### Scenario: Mixed result
- **WHEN** a download of 10 files ends with 6 downloaded, 3 already present and 1 failed
- **THEN** the summary shows these counts and the failed file's name and reason
