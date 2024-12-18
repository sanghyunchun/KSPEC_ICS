#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Mingyeong Yang (mmingyeong@kasi.re.kr)
# @Date: 2024-05-16
# @Filename: gfa_actions.py

import os
import json
import shutil
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed

from .gfa_logger import gfa_logger
from .gfa_controller import gfa_controller
from .gfa_astrometry import gfa_astrometry
from .gfa_guider import gfa_guider

logger = gfa_logger(__file__)

gfa_relative_config_path = "etc/cams.json"
ast_relative_config_path = "etc/test.json"

def get_config_path(relative_config_path):
    """
    Calculate and return the absolute path of the configuration file.

    Parameters
    ----------
    relative_config_path : str
        The relative path of the configuration file.

    Returns
    -------
    str
        Absolute path of the configuration file.

    Raises
    ------
    FileNotFoundError
        If the configuration file does not exist at the calculated path.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, relative_config_path)

    if not os.path.isfile(config_path):
        logger.error(f"Config file not found: {config_path}")
        raise FileNotFoundError(f"Config file not found: {config_path}")

    logger.info(f"Configuration file found: {config_path}")
    return config_path

def initialize():
    global gfa_config_path, controller, ast_config_path, astrometry, guider
    
    gfa_config_path = get_config_path(gfa_relative_config_path)
    controller = gfa_controller(gfa_config_path, logger)

    ast_config_path = get_config_path(ast_relative_config_path)
    astrometry = gfa_astrometry(ast_config_path, logger)
    guider = gfa_guider(ast_config_path, logger)

initialize()

class gfa_actions:
    """
    A class to handle GFA actions such as grabbing images, guiding, and controlling the cameras.
    """

    def __init__(self):
        pass

    @staticmethod
    async def grab(CamNum=0, ExpTime=1, Bininng=4):
        """
        Grab an image from the specified camera(s).
        """
        grab_save_path = "/opt/kspec_gfa_controller/Image/grab"
        response = {}

        try:
            if isinstance(CamNum, int):
                if CamNum == 0:
                    logger.info(f"Grabbing image from all cameras with ExpTime={ExpTime}, Binning={Bininng}")
                    await controller.grab(CamNum, ExpTime, Bininng, output_dir=grab_save_path)
                    response = {
                        "status": "success",
                        "message": "Images grabbed from all cameras.",
                        "CamNum": CamNum,
                        "ExpTime": ExpTime,
                        "Binning": Bininng
                    }
                else:
                    logger.info(f"Grabbing image from camera {CamNum} with ExpTime={ExpTime}, Binning={Bininng}")
                    await controller.grabone(CamNum, ExpTime, Bininng, output_dir=grab_save_path)
                    response = {
                        "status": "success",
                        "message": f"Image grabbed from camera {CamNum}.",
                        "CamNum": CamNum,
                        "ExpTime": ExpTime,
                        "Binning": Bininng
                    }
            elif isinstance(CamNum, list):
                logger.info(f"Grabbing image from cameras {CamNum} with ExpTime={ExpTime}, Binning={Bininng}")
                await controller.grab(CamNum, ExpTime, Bininng, output_dir=grab_save_path)
                response = {
                    "status": "success",
                    "message": f"Images grabbed from cameras {CamNum}.",
                    "CamNum": CamNum,
                    "ExpTime": ExpTime,
                    "Binning": Bininng
                }
            else:
                logger.error(f"Wrong Input {CamNum}")
                raise ValueError(f"Wrong Input {CamNum}")

        except Exception as e:
            logger.error(f"Error occurred: {str(e)}")
            response = {
                "status": "error",
                "message": str(e),
                "CamNum": CamNum,
                "ExpTime": ExpTime,
                "Binning": Bininng
            }

        return json.dumps(response)

    @staticmethod
    async def guiding():
        """
        The main guiding loop that grabs images, processes them with astrometry, and calculates offsets.
        """
        response = {}
        try:
            CamNum = 0
            ExpTime = 1
            Bininng = 4
            flag = False
            
            logger.info("Guiding starts...")
            
            logger.info("Step #1: Grab an image")
            #await controller.grab(CamNum, ExpTime, Bininng, output_dir="/opt/kspec_gfa_controller/Image/raw")
            
            logger.info("Step #2: Astrometry...")
            astrometry.preproc()
            
            logger.info("Step #3: Calculating the offset...")
            fdx, fdy = guider.exe_cal()
            logger.info(f"Offsets calculated: fdx={fdx}, fdy={fdy}")
            response = {
                "status": "success",
                "message": "Guiding completed successfully.",
                "offsets": {"fdx": fdx, "fdy": fdy}
            }
        except Exception as e:
            logger.error(f"Error occurred during guiding: {str(e)}")
            response = {
                "status": "error",
                "message": str(e)
            }

        return json.dumps(response)

    @staticmethod
    def status():
        """
        Check and log the status of all cameras.
        """
        response = {}
        try:
            logger.info("Checking status of all cameras.")
            status_info = controller.status()
            response = {
                "status": "success",
                "message": "Camera status retrieved successfully.",
                "status_info": status_info
            }
        except Exception as e:
            logger.error(f"Error occurred while checking status: {str(e)}")
            response = {
                "status": "error",
                "message": str(e)
            }

        return json.dumps(response)
    
    @staticmethod
    def ping(CamNum=0):
        """
        Ping the specified camera(s) to check connectivity.
        """
        response = {}
        try:
            if CamNum == 0:
                logger.info("Pinging all cameras.")
                for n in range(6):
                    index = n + 1
                    controller.ping(index)
                response = {
                    "status": "success",
                    "message": "Pinging all cameras completed."
                }
            else:
                logger.info(f"Pinging camera {CamNum}.")
                controller.ping(CamNum)
                response = {
                    "status": "success",
                    "message": f"Camera {CamNum} pinged successfully."
                }
        except Exception as e:
            logger.error(f"Error occurred while pinging cameras: {str(e)}")
            response = {
                "status": "error",
                "message": str(e),
                "CamNum": CamNum
            }

        return json.dumps(response)

    @staticmethod
    def cam_params(CamNum=0):
        """
        Retrieve and log parameters from the specified camera(s).
        """
        response = {}
        try:
            if CamNum == 0:
                logger.info("Retrieving parameters for all cameras.")
                params = []
                for n in range(6):
                    index = n + 1
                    param = controller.cam_params(index)
                    params.append(param)
                response = {
                    "status": "success",
                    "message": "Parameters retrieved for all cameras.",
                    "params": params
                }
            else:
                logger.info(f"Retrieving parameters for camera {CamNum}.")
                param = controller.cam_params(CamNum)
                response = {
                    "status": "success",
                    "message": f"Parameters retrieved for camera {CamNum}.",
                    "params": param
                }
        except Exception as e:
            logger.error(f"Error occurred while retrieving camera parameters: {str(e)}")
            response = {
                "status": "error",
                "message": str(e),
                "CamNum": CamNum
            }

        return json.dumps(response)

