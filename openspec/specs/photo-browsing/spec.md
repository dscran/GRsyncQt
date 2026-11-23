# photo-browsing Specification

## Purpose

Lets the user see what is on the camera's card as a grid of correctly rotated
thumbnails, look at a shot in a larger preview, and select shots to download,
without downloading full files.

## Requirements

### Requirement: Files grouped into shots
The app SHALL group the camera's files into shots. A JPG and a DNG with the same
folder and base name form one shot. A JPG or DNG without a partner, and every
MOV, form a shot of their own. Each shot SHALL show which file types it has.

#### Scenario: JPG+DNG pair
- **WHEN** the card holds `113RICOH/R0006483.JPG` and `113RICOH/R0006483.DNG`
- **THEN** the grid shows one shot `R0006483` marked as having JPG and RAW

#### Scenario: Unpaired files and video
- **WHEN** the card holds `100RICOH/R0000002.JPG` without a DNG, `100RICOH/R0000005.DNG` without a JPG, and `100RICOH/R0000003.MOV`
- **THEN** the grid shows three shots, marked JPG, RAW and video respectively

#### Scenario: Same base name in different folders
- **WHEN** `100RICOH/R0000001.JPG` and `101RICOH/R0000001.DNG` both exist
- **THEN** they are two separate shots

### Requirement: Newest shots first
The grid SHALL list shots newest first, using the camera's folder and file
numbering order. Each shot SHALL show its file name.

#### Scenario: Order across folders
- **WHEN** the card holds shots in `112RICOH` and `113RICOH`
- **THEN** the shots of `113RICOH` come first, highest file number first

### Requirement: Thumbnails load lazily, visible first
The app SHALL request thumbnails only for shots that are visible or about to
become visible, the visible ones first. A shot SHALL show a placeholder until
its thumbnail arrives, and the grid SHALL stay responsive while thumbnails load.

#### Scenario: Large card
- **WHEN** the card holds 1243 files and the window shows about 30 shots
- **THEN** thumbnails are requested for the visible shots first, and none is requested for a shot the user never scrolls near

#### Scenario: Scrolling changes priority
- **WHEN** the user scrolls to another part of the grid while thumbnails are still loading
- **THEN** the newly visible shots are loaded next, before the ones that scrolled out of view

#### Scenario: Responsive while loading
- **WHEN** thumbnails are loading
- **THEN** the user can scroll, select shots and look at the preview pane without the window freezing

### Requirement: Thumbnail source per shot
The app SHALL use the small JPG thumbnail for shots with a JPG, the DNG's
thumbnail for RAW-only shots and the MOV's thumbnail for videos, scaled to the
grid size. Black letterbox bars around a JPG thumbnail SHALL NOT be shown.

#### Scenario: Pair uses the JPG thumbnail
- **WHEN** a shot has a JPG and a DNG
- **THEN** its thumbnail is fetched from the JPG only

#### Scenario: Letterbox removed
- **WHEN** a 3:2 JPG thumbnail arrives as 160×120 with black bars at the top and bottom
- **THEN** the grid shows the picture without the black bars

### Requirement: Images shown upright
Thumbnails and previews SHALL be rotated according to the orientation the
camera reports for the file, because the images themselves carry no
orientation data.

#### Scenario: Portrait shot
- **WHEN** the camera reports orientation 6 for a shot
- **THEN** its thumbnail and preview are shown rotated 90° clockwise, in portrait format

#### Scenario: Orientation unknown
- **WHEN** the orientation of a shot cannot be read
- **THEN** its thumbnail is shown unrotated, and the grid keeps working

### Requirement: Preview pane
The window SHALL show the grid and, in a resizable split to its right, a large
preview of the current shot (the shot last clicked or moved to with the
keyboard), rotated upright, with the shot's file names, capture date, file
sizes and exposure data. The split position SHALL be remembered across
sessions.

#### Scenario: Current shot shown
- **WHEN** the user clicks a shot or moves to it with the arrow keys
- **THEN** the preview pane shows that shot upright, with its file names, capture date, sizes and exposure data

#### Scenario: Moving quickly through shots
- **WHEN** the user holds an arrow key and moves across 10 shots in a second
- **THEN** the preview of the shot the user stops on loads first, and previews of shots only passed over are not all requested

#### Scenario: Video preview
- **WHEN** the current shot is a video
- **THEN** the preview pane shows the video's preview frame (the app does not play videos)

#### Scenario: No current shot
- **WHEN** the card is empty or the app is not connected
- **THEN** the preview pane is empty and the grid keeps working

### Requirement: Zoom the preview
The preview SHALL fit the pane by default. The user SHALL be able to zoom in
and out with Ctrl+mouse wheel and with buttons (zoom in, zoom out, fit,
100 %), and to pan a zoomed image by dragging. The zoomed image SHALL be the
largest preview the camera serves, which is 720×480 (a probe found no larger
one).

#### Scenario: Zoom in and pan
- **WHEN** the user presses Ctrl and turns the mouse wheel up over the preview, then drags the image
- **THEN** the image is shown larger around the pointer and moves with the drag

#### Scenario: Back to fit
- **WHEN** the user chooses fit, or another shot becomes current
- **THEN** the whole preview fits the pane again

### Requirement: Exposure data shown
Under each thumbnail and in the preview pane, the app SHALL show the shot's
ISO, aperture, shutter speed and exposure compensation, taken from the
thumbnail source file's details, as soon as they are known. Videos SHALL show
no exposure data.

#### Scenario: Measured values
- **WHEN** the camera reports `sv` `3200`, `av` `4.5`, `tv` `1.4` and `xv` `0.0` for a shot
- **THEN** the shot shows `ISO 3200 · f/4.5 · 1/4 s · 0 EV`

#### Scenario: Long exposure and compensation
- **WHEN** the camera reports `tv` `2.1` and `xv` `-1.3`
- **THEN** the shutter speed shows as `2 s` and the compensation as `−1.3 EV`

#### Scenario: Video
- **WHEN** the shot is a video
- **THEN** no exposure data is shown for it

### Requirement: Thumbnail size
The user SHALL be able to change the thumbnail size between 96 and 320 pixels
with a slider in the window and with Ctrl+mouse wheel over the grid. The size
SHALL be remembered across sessions. Above 160 pixels, JPG shots SHALL use the
camera's preview image instead of the 160×120 thumbnail, so they stay sharp.

#### Scenario: Ctrl+mouse wheel
- **WHEN** the user presses Ctrl and turns the mouse wheel up over the grid
- **THEN** the thumbnails get larger, the slider follows, and the current shot stays in view

#### Scenario: Large thumbnails
- **WHEN** the thumbnail size is above 160 pixels
- **THEN** shots with a JPG load the preview image for their thumbnail, and a shot whose preview was already loaded makes no new request

#### Scenario: Size remembered
- **WHEN** the user restarts the app
- **THEN** the thumbnail size chosen in the previous session is used

### Requirement: Thumbnails reused within a session
The app SHALL keep thumbnails, previews and file details it has fetched for the
rest of the session, and SHALL NOT request them again. Nothing SHALL be kept on
disk after the app quits.

#### Scenario: Scrolling back
- **WHEN** the user scrolls away from shots whose thumbnails loaded and back again
- **THEN** the thumbnails appear at once without new camera requests

### Requirement: Selecting shots
The user SHALL be able to select and deselect shots in the grid, using mouse
clicks with the usual Ctrl/Shift extensions and keyboard navigation, and SHALL
be able to select all shots and clear the selection. The number of selected
shots SHALL be shown.

#### Scenario: Range selection
- **WHEN** the user clicks one shot and Shift-clicks another
- **THEN** both shots and all shots between them are selected, and the count is shown

#### Scenario: Select all
- **WHEN** the user chooses select all
- **THEN** every shot on the card is selected, including ones without a loaded thumbnail

### Requirement: Already downloaded files marked
For each file of a shot (JPG, RAW, video), the grid SHALL show whether it is
already in the destination folder, judged by name and size as soon as the app
knows the file's size.

#### Scenario: Pair fully downloaded
- **WHEN** a visible shot's JPG and DNG already exist in the destination folder with the sizes the camera reports
- **THEN** both the JPG and the RAW markers of the shot show them as downloaded

#### Scenario: Only the JPG downloaded
- **WHEN** a visible shot's JPG exists locally with the same size but its DNG does not
- **THEN** the JPG marker shows downloaded and the RAW marker does not

#### Scenario: Destination changed
- **WHEN** the user picks a different destination folder
- **THEN** the downloaded markers are re-evaluated against the new folder

### Requirement: Refresh the shot list
The user SHALL be able to reload the shot list, for example after taking more
pictures while connected. Selections of shots still on the card SHALL be kept.

#### Scenario: New shot after refresh
- **WHEN** the user takes a picture and then refreshes
- **THEN** the new shot appears at the top of the grid and the previous selection is kept
