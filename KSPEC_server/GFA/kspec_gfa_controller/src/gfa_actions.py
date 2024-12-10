#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Mingyeong Yang (mmingyeong@kasi.re.kr)
# @Date: 2024-05-16
# @Filename: gfa_actions.py

import os
import shutil
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed

from kspec_gfa_controller.src.gfa_logger import gfa_logger
from kspec_gfa_controller.src.gfa_controller import gfa_controller
from kspec_gfa_controller.src.gfa_astrometry import gfa_astrometry
from kspec_gfa_controller.src.gfa_guider import gfa_guider
import json

logger = gfa_logger(__file__)

gfa_relative_config_path = "etc/cams.json"
ast_relative_config_path = "etc/astrometry_params.json"
grab_file_path = "grab_save"

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
    async def auto_guiding():
        """
        Start the auto-guiding loop, which will continuously grab images and process them until stopped.
        """
        stop_event = asyncio.Event()

        # Launching the loop and input checking as concurrent tasks
        loop_task = asyncio.create_task(guiding_loop(stop_event))
        input_task = asyncio.create_task(check_for_input(stop_event))

        # Shield loop_task from being canceled until check_for_input finishes
        await asyncio.gather(asyncio.shield(loop_task), input_task)

    @staticmethod
    async def grab(CamNum=0, ExpTime=1, Bininng=4, save=True):
        """
        Grab an image from the specified camera(s).

        Parameters
        ----------
        CamNum : int or list of int
            The camera number(s) to grab images from.
            If 0, grabs from all cameras.
        ExpTime : float, optional
            Exposure time in seconds (default is 1).
        Bininng : int, optional
            Binning size (default is 4).
        save : bool, optional
            Whether to save the grabbed image (default is True).

        Raises
        ------
        ValueError
            If CamNum is neither an integer nor a list of integers.
        """
        if isinstance(CamNum, int):
            if CamNum == 0:
                logger.info(f"Grabbing image from all cameras with ExpTime={ExpTime}, Binning={Bininng}, save={save}")
                await controller.grab(CamNum, ExpTime, Bininng)
            else:
                logger.info(f"Grabbing image from camera {CamNum} with ExpTime={ExpTime}, Binning={Bininng}, save={save}")
                await controller.grabone(CamNum, ExpTime, Bininng)
        elif isinstance(CamNum, list):
            logger.info(f"Grabbing image from cameras {CamNum} with ExpTime={ExpTime}, Binning={Bininng}, save={save}")
            await controller.grab(CamNum, ExpTime, Bininng)
        else:
            logger.error(f"Wrong Input {CamNum}")
            raise ValueError(f"Wrong Input {CamNum}")
        
        dest_folder = "grab_archive"
        if not save:
            empty_folder(grab_file_path)
        else:
            copy_folder(grab_file_path, dest_folder)
            empty_folder(grab_file_path)

        comments='Autoguiding now.......'
        dict_data={'inst': 'GFA', 'savedata': 'False','filename': 'None','comments': comments}
        rsp=json.dumps(dict_data)
        return rsp

# --------------------------------------------------------------------------------------------------------------------------------------

async def guiding_loop(stop_event):
    """
    The main guiding loop that grabs images, processes them with astrometry, and calculates offsets.

    Parameters
    ----------
    stop_event : asyncio.Event
        Event to signal when to stop the loop.
    """
    CamNum = 0
    ExpTime = 1
    Bininng = 4
    save = False
    flag = False
    
    while not stop_event.is_set():
        logger.info("Guiding loop starts...")
        
        # Step #1: Grab an image
        await controller.grab(CamNum, ExpTime, Bininng)
        
        # Step #2: Perform astrometry
        if not flag:
            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = [executor.submit(astrometry.combined_function, flname) for flname in astrometry.astrometry_params]
                
                crval1_results = []
                crval2_results = []
                
                for future in as_completed(futures):
                    crval1, crval2 = future.result()
                    crval1_results.append(crval1)
                    crval2_results.append(crval2)

                logger.info(f"Astrometry results - CRVAL1: {crval1_results}, CRVAL2: {crval2_results}")

                astrometry.star_catalog()    
                astrometry.rm_tempfiles()
                flag = True
        else:
            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = [executor.submit(astrometry.process_file, flname) for flname in astrometry.astrometry_params]
        
        # Step #3: Calculate offsets
        fdx, fdy = guider.exe_cal()
        logger.info(f"Offsets calculated: fdx={fdx}, fdy={fdy}")
        
        await asyncio.sleep(1)  # Asynchronous wait to prevent blocking


async def check_for_input(stop_event):
    """
    Asynchronously check for user input to stop the guiding loop.

    Parameters
    ----------
    stop_event : asyncio.Event
        Event to signal when to stop the loop.
    """
    logger.info("Waiting for user input to stop the loop (press 'qq').")
    while not stop_event.is_set():
        input_char = await asyncio.get_event_loop().run_in_executor(None, input, "")
        if input_char.strip().lower() == 'qq':
            logger.info("Stop command received. Exiting the loop.")
            stop_event.set()
        else:
            logger.warning(f"Received unrecognized input: {input_char.strip()}")
        await asyncio.sleep(0.1)  # Reduce CPU usage with a brief pause

def copy_folder(src_folder, dest_folder):
    # 원본 폴더가 존재하는지 확인
    if os.path.exists(src_folder):
        # 대상 폴더가 이미 존재하지 않는지 확인
        if not os.path.exists(dest_folder):
            try:
                # 폴더 복사
                shutil.copytree(src_folder, dest_folder)
                print(f'Folder copied from {src_folder} to {dest_folder}')
            except Exception as e:
                print(f'Failed to copy folder. Reason: {e}')
        else:
            print(f'The destination folder {dest_folder} already exists')
    else:
        print(f'The source folder {src_folder} does not exist')

def empty_folder(src_folder):
        # 폴더가 존재하는지 확인
        if os.path.exists(src_folder):
            # 폴더 안의 모든 파일과 디렉토리를 삭제
            for filename in os.listdir(src_folder):
                file_path = os.path.join(src_folder, filename)

# --------------------------------------------------------------------------------------------------------------------------------------

def status():
    """
    Check and log the status of all cameras.
    """
    logger.info("Checking status of all cameras.")
    controller.status()

def ping(CamNum=0):
    """
    Ping the specified camera(s) to check connectivity.

    Parameters
    ----------
    CamNum : int, optional
        The camera number to ping. If 0, pings all cameras (default is 0).
    """
    if CamNum == 0:
        logger.info("Pinging all cameras.")
        for n in range(6):
            index = n + 1
            controller.ping(index)
    else:
        logger.info(f"Pinging camera {CamNum}.")
        controller.ping(CamNum)

def cam_params(CamNum=0):
    """
    Retrieve and log parameters from the specified camera(s).

    Parameters
    ----------
    CamNum : int, optional
        The camera number to retrieve parameters from.
        If 0, retrieves from all cameras (default is 0).
    """
    if CamNum == 0:
        logger.info("Retrieving parameters for all cameras.")
        for n in range(6):
            index = n + 1
            controller.cam_params(index)
    else:
        logger.info(f"Retrieving parameters for camera {CamNum}.")
        controller.cam_params(CamNum)
