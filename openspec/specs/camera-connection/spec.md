# camera-connection Specification

## Purpose

Lets the app find a Ricoh GR III or GR IIIx on the camera's Wi-Fi, confirm it is a
supported model, report its state, and talk to it without ever changing anything
on the camera.

## Requirements

### Requirement: Connect on start and on request
The app SHALL try to connect to the camera at `http://192.168.0.1/` when it starts
and whenever the user asks to retry. A command-line option SHALL allow another
base URL, for testing.

#### Scenario: Camera reachable at start
- **WHEN** the app starts while the computer is on the camera's Wi-Fi
- **THEN** the app shows the camera as connected and loads the shot list without further user action

#### Scenario: Camera not reachable
- **WHEN** the app starts and the camera does not answer within the connect timeout
- **THEN** the app shows that it is not connected, suggests joining the camera's Wi-Fi, and offers a retry

#### Scenario: Retry after joining the Wi-Fi
- **WHEN** the user joins the camera's Wi-Fi and chooses retry
- **THEN** the app connects and loads the shot list

#### Scenario: Other base URL
- **WHEN** the app is started with the host option set to `http://127.0.0.1:8080/`
- **THEN** every camera request goes to that base URL

### Requirement: Supported models only
The app SHALL accept a camera only if its reported model is `RICOH GR III` or
`RICOH GR IIIx`. Any other answer SHALL be treated as not connected, and the
reported model SHALL be shown to the user.

#### Scenario: GR III
- **WHEN** the camera reports model `RICOH GR III`
- **THEN** the app connects and shows the model name

#### Scenario: Unsupported device
- **WHEN** the address answers with a model `RICOH GR II`, or with something that is not camera properties (for example a router's web page)
- **THEN** the app does not connect, and says the device is not a supported camera, naming the model if one was reported

### Requirement: Battery level shown
While connected, the app SHALL show the camera's battery level from the camera
properties. It SHALL warn before a download starts when the level is below 15 %.

#### Scenario: Battery shown on connect
- **WHEN** the app connects to a camera reporting battery 87
- **THEN** the battery level 87 % is visible in the window

#### Scenario: Low battery warning
- **WHEN** the battery level is 10 % and the user starts a download
- **THEN** the app warns about the low battery and lets the user continue or cancel

### Requirement: Camera secrets never exposed
The app SHALL NOT display, log or save the camera's Wi-Fi password, SSID,
serial number, MAC address or GPS position, even though the camera properties
include them.

#### Scenario: Properties handled
- **WHEN** the app reads the camera properties and runs with logging at its most verbose level
- **THEN** none of the values of `key`, `ssid`, `serialNo`, `macAddress` or `gpsInfo` appears in the window, the log output or any file the app writes

### Requirement: Read-only toward the camera
The app SHALL send only GET requests to the camera. It SHALL NOT delete files,
change settings or power the camera off, and it SHALL NOT offer any of these
actions.

#### Scenario: Whole session
- **WHEN** the user connects, browses, previews, downloads and quits the app
- **THEN** the camera received only GET requests, and none to `/v1/device/finish`

#### Scenario: Quitting
- **WHEN** the user quits the app while connected
- **THEN** the camera stays on with its Wi-Fi enabled

### Requirement: Connection loss detected
The app SHALL detect when the camera stops answering during a session. It SHALL
show the disconnected state and offer a retry that keeps the current shot list
and selection.

#### Scenario: Camera Wi-Fi drops while browsing
- **WHEN** thumbnail requests fail because the camera no longer answers
- **THEN** the app shows it is disconnected and stops sending requests until the user retries

#### Scenario: Reconnect keeps the selection
- **WHEN** the user retries after a connection loss and the camera answers again
- **THEN** the shot list is refreshed and shots selected before the loss that are still on the card remain selected
