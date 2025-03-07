# Changelog

## Version 0.1.0
- **Date**: 2023-12-11
- Created repository
- Initialized the repository and Controller

## Version 0.2.0
- **Date**: 2024-01-19
- Implemented `gfa_controller` function
- Implemented functions in `etc.` class
- Added commands for `status` and `grab`
- Updated dependencies with Poetry
- Updated Sphinx documentation
- Updated README

## Version 0.3.0
- **Date**: 2024-02-14
- Added descriptive comments to classes and functions
- Added `ping()` function and command
- Updated `gfa_logger`: logging system
- Updated `gfa_exceptions`: exception handling system
- Applied logging system to `gfa_controller` and `gfa_config`
- Applied exception handling to `gfa_controller` and `gfa_config`
- Updated Sphinx documentation with KSPEC logo

## Version 0.4.0
- **Date**: 2024-08-01
- Integrated with `kspec-gfa` draft version
- Updated `cams.yml` with new camera information
- Re-added logger and exception handling
- Modified internal functions in `gfa_controller.py`
- Added new action functions (e.g., `grabone()`, `graball()`) in `gfa_action.py`
- Updated code for asynchronous execution
- Added `main.py` for testing purposes

## Version 0.5.0
- **Date**: 2024-08-09
- **Configuration Updates**:
  - Converted `Cams.yml` to `Cams.json`
  - Updated `controller/src/etc/cams.yml`
  - Initial configuration update for Multicam setup
  - Added connection for Camera 6
- **Code Enhancements**:
  - Updated docstrings and logging code across the project
- **New Feature**:
  - Added function to save images as FITS files in `Gfa_img.py`
- **Function Updates**:
  - Updated `grab()` function in `Gfa_action.py`
  - Updated `grabone()`, `grab()`, and `process_camera()` functions in `Gfa_controller.py`
- **Code Quality**:
  - Applied code formatting and linting using `black`, `flake8`, `isort`, and `ruff`

## Version 0.6.0
- **Date**: 2024-08-09
- **Configuration Updates**:
  - Updated Ruff configuration file and applied code formatting
- **Documentation**:
  - Made minor updates to the README and added a Ruff badge
  - Updated Sphinx documentation
- **CI/CD**:
  - Added GitHub Actions workflow files for Ruff and Sphinx documentation

## Version 0.7.0
- **Date**: 2024-10-21
- **Changes to `dictionary_data.json`**:
  - Updated guiding image storage path to `raw/, procimg/, tempfiles/, astroimg`.
  - Updated grab image storage path to: `grab_save_path = "/opt/kspec_gfa_controller/Image/grab"`.
  - Reorganized parameters and verified their usage within the code.
- **Folder Access Permissions**:
  - Modified `kspec_gfa_controller/scripts/set_permissions.sh` to handle permission updates.
  - Adjusted folder access permissions for `/opt/kspec_gfa_controller/`.
- **General Updates**:
  - Changed the log file storage path to `/opt/kspec_gfa_controller/log`.
  - Command outputs are now returned in JSON format.
- **Guiding Functionality**:
  - Conducted tests for `guiding()` and confirmed correct operation in test env.
  - Updated astrometry and guider main sections to final execution functions:
    - `def preproc(self):`
    - `def exe_cal(self):`

## Version 1.0.0
- **Date**: 2024-11-15
- **Changes to GFAAstrometry & GFAGuider**:
  - Revised both classes for improved functionality and maintainability.
  - Completed tests confirming the changes work as expected.
- **Logging & Docstrings**:
  - Reviewed and updated logging statements for clarity and consistency.
  - Added/refined docstrings to align with code style standards.
- **Code Style**:
  - Conducted a comprehensive code style review (including linting/formatting).
  - Ensured internal consistency and adherence to the project’s style guidelines.
- **Image Save Path**:
  - Updated image save path in modules.
  - Verified changes through end-to-end tests.

## Version 1.1.0
- **Date**: 2025-02-25
- **Changes to Camera Status Functionality**:
  - Refactored `status()` method to return camera standby status as `True` or `False` instead of logging-only.
  - Ensured cameras in standby mode return `True`, while connection failures or non-standby states return `False`.
- **Logging & Error Handling**:
  - Improved logging to include camera IP addresses and error messages for better debugging.
- **Code Optimization**:
  - Used a dictionary to store camera statuses (`{"Cam1": True, "Cam2": False, ...}`) for improved accessibility.
  - Verified changes with runtime tests to ensure expected behavior.
