#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Mingyeong Yang (mmingyeong@kasi.re.kr)
# @Date: 2025-06-30
# @Filename: gfa_environment.py

import os
import json
from typing import List, Optional, Literal

from .gfa_controller import GFAController
from .gfa_logger import GFALogger
from .gfa_astrometry import GFAAstrometry
from .gfa_guider import GFAGuider

logger = GFALogger(__file__)

# Type hint for role selection
CameraRole = Literal["plate", "finder"]


def get_config_path(relative_path: str) -> str:
    """
    Return absolute path from relative config file path.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    full_path = os.path.join(base_dir, relative_path)
    if not os.path.isfile(full_path):
        logger.error(f"Configuration file not found: {full_path}")
        raise FileNotFoundError(f"Configuration file not found: {full_path}")
    return full_path


def get_camera_ids(config_path: str, role: CameraRole) -> List[int]:
    """
    Parse JSON config and return list of camera IDs for a given role.
    """
    with open(config_path, "r") as f:
        config = json.load(f)

    cam_elements = config["GfaController"]["Elements"]["Cameras"]["Elements"]
    camera_ids = []

    for cam_key, cam_data in cam_elements.items():
        cam_number = cam_data.get("Number", None)
        if cam_number is None:
            continue
        if role == "plate" and cam_number in range(1, 7):
            camera_ids.append(cam_number)
        elif role == "finder" and cam_number == 7:
            camera_ids.append(cam_number)

    return sorted(camera_ids)


class GFAEnvironment:
    """
    Generalized environment class to support both plate and finder camera sets.
    """

    def __init__(
        self,
        gfa_config_path: str,
        ast_config_path: Optional[str],
        role: CameraRole = "plate",
    ):
        self.logger = logger
        self.gfa_config_path = gfa_config_path
        self.ast_config_path = ast_config_path
        self.role = role

        self.camera_ids = get_camera_ids(self.gfa_config_path, role)
        self.logger.info(
            f"Initialized GFAEnvironment with role '{role}' and cameras {self.camera_ids}"
        )

        if role == "plate":
            self.controller = GFAController(self.gfa_config_path, self.logger)
            self.astrometry = GFAAstrometry(self.ast_config_path, self.logger)
            self.guider = GFAGuider(self.ast_config_path, self.logger)
        elif role == "finder":
            self.controller = GFAController(self.gfa_config_path, self.logger)
            self.astrometry = None
            self.guider = None

    def shutdown(self):
        self.logger.info(f"Shutting down environment ({self.role})")
        if self.role == "finder":
            self.controller.close_camera(7)
        else:
            for cam_id in self.camera_ids:
                self.controller.close_camera(cam_id)


def create_environment(role: CameraRole = "plate") -> GFAEnvironment:
    gfa_config_path = get_config_path("etc/cams.json")
    ast_config_path = (
        get_config_path("etc/astrometry_params.json") if role == "plate" else None
    )
    return GFAEnvironment(gfa_config_path, ast_config_path, role=role)
