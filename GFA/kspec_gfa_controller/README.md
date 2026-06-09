# kspec_gfa_controller

![Versions](https://img.shields.io/badge/python-3.9+-blue)
![Ruff](https://github.com/mmingyeong/kspec_gfa_controller/actions/workflows/ruff.yml/badge.svg)
[![Documentation Status](https://readthedocs.org/projects/kspec-gfa/badge/?version=latest)](https://kspec-gfa.readthedocs.io/en/latest/?badge=latest)
[![codecov](https://codecov.io/github/mmingyeong/kspec_gfa_controller/graph/badge.svg?token=DDBX989XZ2)](https://codecov.io/github/mmingyeong/kspec_gfa_controller)
[![tests](https://github.com/mmingyeong/kspec_gfa_controller/actions/workflows/tests.yml/badge.svg)](https://github.com/mmingyeong/kspec_gfa_controller/actions/workflows/tests.yml)

# kspec_gfa_controller

KSPEC-GFA control software for **guiding**, **focusing**, and **image acquisition** during KSPEC observations.  
It communicates with **seven Basler ace 2 Pro (a2A5328-4gmPRO)** guide cameras via **pypylon** and provides a unified command-style interface for the K-SPEC ICS.

## Hardware (summary)
- 7 × Basler ace 2 Pro (Sony IMX540 mono CMOS, SDSS r-band)
- Plate cameras: Cam1–Cam6, Finder camera: Cam7
- Typical operation: 4×4 binning during observations

## Core capabilities
- Centralized control of the GFA camera system (single / multi-camera)
- Configurable image acquisition (exposure time, binning, transport settings)
- Astrometry-based offset computation and image-quality estimation (FWHM)
- Monitoring/diagnostics (status, ping, camera parameters)
- Fault detection with safe stop / error reporting to the ICS

## Command-style API (implemented)
- `status` — camera operational status
- `ping` — network connectivity check
- `cam_params` — camera configuration/parameters
- `grab` — capture image(s) from selected camera(s)
- `guiding` — full pipeline: acquisition → astrometry → offset + FWHM
- `shutdown` — close sessions and terminate safely

## Installation
Clone the repository:

```console
git clone https://github.com/mmingyeong/kspec_gfa_controller.git
```

## Notes

This project uses pypylon as the middleware to communicate with Basler cameras and is designed to interface with the K-SPEC ICS through a minimal, unified set of operations.
