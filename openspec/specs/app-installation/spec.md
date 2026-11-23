# app-installation Specification

## Purpose

Lets a user install the app from a checkout of the repository with pip and start
it with a single command, without publishing it to PyPI.

## Requirements

### Requirement: Installable with pip from the repo
The repository SHALL be installable with `pip install .` (and editable with
`pip install -e .`) from a checkout, pulling in its runtime dependencies.
Development tools SHALL be available as an optional `dev` extra.

#### Scenario: Fresh environment
- **WHEN** a user runs `pip install .` in a checkout using a Python environment with pip and network access
- **THEN** the installation succeeds and installs PySide6 and requests if they are missing

#### Scenario: Development install
- **WHEN** a developer runs `pip install -e ".[dev]"`
- **THEN** the test tools are installed as well, and source changes take effect without reinstalling

### Requirement: Launch command
Installing SHALL provide a `grsync-qt` command that starts the app. Running the
package as a module SHALL start it too.

#### Scenario: Start from the command
- **WHEN** the user runs `grsync-qt` after installing
- **THEN** the app window opens

#### Scenario: Start as a module
- **WHEN** the user runs `python -m grsync_qt`
- **THEN** the app window opens

#### Scenario: Help
- **WHEN** the user runs `grsync-qt --help`
- **THEN** the available options, including the camera host option, are listed and the app exits without opening a window

### Requirement: Only app code installed
The installed package SHALL contain the app only. The probe spike, its fake
camera, the documentation and the tests SHALL NOT be installed.

#### Scenario: Installed files
- **WHEN** the package is installed
- **THEN** no module from `spike/` or `tests/` is importable from the installed package
