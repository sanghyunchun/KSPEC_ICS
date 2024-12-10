#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Mingyeong Yang (mmingyeong@kasi.re.kr)
# @Date: 2024-06-26
# @Filename: adc_controller.py

import os
import json
import time
import asyncio
from nanotec_nanolib import Nanolib

__all__ = ["AdcController"]

class AdcController:
    """
    Interacts with a KSPEC ADC system over a serial port.

    Attributes
    ----------
    CONFIG_FILE : str
        Path to the JSON configuration file.
    logger : logging.Logger
        Logger instance for logging messages.
    nanolib_accessor : Nanolib.NanoLibAccessor
        Instance for accessing the Nanolib API.
    devices : dict
        Dictionary for managing device handles and connection states.
    selected_bus_index : int
        Index of the selected bus hardware.
    """

    CONFIG_FILE = "adc_config.json"

    def __init__(self, logger):
        """
        Initializes the AdcController.

        Parameters
        ----------
        logger : logging.Logger
            Logger instance for debugging and informational logs.
        """
        self.logger = logger
        self.nanolib_accessor = Nanolib.getNanoLibAccessor()
        self.logger.debug("Initializing AdcController")
        self.devices = {
            1: {"handle": None, "connected": False},
            2: {"handle": None, "connected": False},
        }
        self.selected_bus_index = self._load_selected_bus_index()

    def _load_selected_bus_index(self) -> int:
        """
        Loads the selected bus index from a JSON configuration file.

        Returns
        -------
        int
            The selected bus index from the configuration file.
            Defaults to 1 if the file does not exist or is invalid.

        Notes
        -----
        If the configuration file is missing or cannot be read, a warning is logged, 
        and the default value is used.
        """
        default_index = 1
        if os.path.exists(self.CONFIG_FILE):
            try:
                with open(self.CONFIG_FILE, "r") as file:
                    config = json.load(file)
                    return config.get("selected_bus_index", default_index)
            except (json.JSONDecodeError, IOError) as e:
                self.logger.error(f"Error reading configuration file: {e}")
        else:
            self.logger.warning(f"Configuration file {self.CONFIG_FILE} not found. Using default index {default_index}.")
        return default_index

    def find_devices(self):
        """
        Finds devices connected to the selected bus and initializes them.

        Raises
        ------
        Exception
            If no bus hardware IDs are found or if there is an error during initialization.
        """
        self.logger.info("Starting the process to find devices...")
        list_available_bus = self.nanolib_accessor.listAvailableBusHardware()
        if list_available_bus.hasError():
            raise Exception(f"Error: listAvailableBusHardware() - {list_available_bus.getError()}")

        bus_hardware_ids = list_available_bus.getResult()
        if not bus_hardware_ids.size():
            raise Exception("No bus hardware IDs found.")

        for i, bus_id in enumerate(bus_hardware_ids):
            self.logger.info(f"ID {i}: {bus_id.toString() if hasattr(bus_id, 'toString') else str(bus_id)}")

        ind = self.selected_bus_index
        self.adc_motor_id = bus_hardware_ids[ind]
        self.logger.info(f"Selected bus hardware ID: {self.adc_motor_id}")

        # Configure options
        self.adc_motor_options = Nanolib.BusHardwareOptions()
        self.adc_motor_options.addOption(
            Nanolib.Serial().BAUD_RATE_OPTIONS_NAME, Nanolib.SerialBaudRate().BAUD_RATE_115200
        )
        self.adc_motor_options.addOption(
            Nanolib.Serial().PARITY_OPTIONS_NAME, Nanolib.SerialParity().EVEN
        )

        # Open bus hardware
        open_bus = self.nanolib_accessor.openBusHardwareWithProtocol(self.adc_motor_id, self.adc_motor_options)
        if open_bus.hasError():
            raise Exception(f"Error: openBusHardwareWithProtocol() - {open_bus.getError()}")

        # Scan devices
        scan_devices = self.nanolib_accessor.scanDevices(self.adc_motor_id, callbackScanBus)
        if scan_devices.hasError():
            raise Exception(f"Error: scanDevices() - {scan_devices.getError()}")

        self.device_ids = scan_devices.getResult()
        if not self.device_ids.size():
            raise Exception("No devices found during scan.")

        for i, device_id in enumerate(self.device_ids):
            if i + 1 in self.devices:
                handle_result = self.nanolib_accessor.addDevice(device_id)
                if handle_result.hasError():
                    raise Exception(f"Error adding device {i + 1}: {handle_result.getError()}")
                self.devices[i + 1]["handle"] = handle_result.getResult()
                self.logger.info(f"Device {i + 1} added successfully.")

    def connect(self, motor_number=0):
        """
        Connects the specified motor or all motors to the bus.

        Parameters
        ----------
        motor_number : int, optional
            The motor number to connect (default is 0, which connects all motors).
        """
        self._set_connection_state(motor_number, connect=True)

    def disconnect(self, motor_number=0):
        """
        Disconnects the specified motor or all motors from the bus.

        Parameters
        ----------
        motor_number : int, optional
            The motor number to disconnect (default is 0, which disconnects all motors).
        """
        self._set_connection_state(motor_number, connect=False)

    def _set_connection_state(self, motor_number, connect):
        """
        Generalized method for connecting or disconnecting devices.

        Parameters
        ----------
        motor_number : int
            The motor number to connect or disconnect.
        connect : bool
            True to connect the motor, False to disconnect.

        Raises
        ------
        ValueError
            If the motor number is invalid.
        Exception
            If there is an error during connection or disconnection.
        """
        try:
            if motor_number not in [0, 1, 2]:
                raise ValueError("Invalid motor number. Must be 0, 1, or 2.")

            motors = [motor_number] if motor_number != 0 else [1, 2]
            for motor in motors:
                device = self.devices[motor]
                if connect:
                    if device["connected"]:
                        self.logger.info(f"Device {motor} is already connected.")
                    else:
                        result = self.nanolib_accessor.connectDevice(device["handle"])
                        if result.hasError():
                            raise Exception(f"Error: connectDevice() - {result.getError()}")
                        device["connected"] = True
                        self.logger.info(f"Device {motor} connected successfully.")
                else:
                    if device["connected"]:
                        result = self.nanolib_accessor.disconnectDevice(device["handle"])
                        if result.hasError():
                            raise Exception(f"Error: disconnectDevice() - {result.getError()}")
                        device["connected"] = False
                        self.logger.info(f"Device {motor} disconnected successfully.")
                    else:
                        self.logger.info(f"Device {motor} was not connected.")

        except Exception as e:
            self.logger.exception(f"An error occurred while {'connecting' if connect else 'disconnecting'}: {e}")
            raise

    def close(self):
        """
        Closes the bus hardware connection.

        Raises
        ------
        Exception
            If there is an error during closing the bus hardware.
        """
        self.logger.debug("Closing all devices...")
        close_result = self.nanolib_accessor.closeBusHardware(self.adc_motor_id)
        if close_result.hasError():
            raise Exception(f"Error: closeBusHardware() - {close_result.getError()}")
        self.logger.info("Bus hardware closed successfully.")


    async def homing(self):
        """
        Move both motors to their home position (Position actual value = 0).

        This method checks the connection state of each motor and moves them to 
        the home position concurrently if they are not already in position. 
        It logs the process and measures the execution time.

        Returns
        -------
        None
            If all motors are successfully moved to the home position or 
            already at the home position.

        Raises
        ------
        Exception
            If any motor is not connected or if there is an error during 
            the homing process.
        """
        self.logger.debug("Starting the homing process for both motors...")
        start_time = time.time()

        try:
            # Check if all required devices are connected
            for motor_id, device in self.devices.items():
                if not device["connected"]:
                    raise Exception(f"Error: Motor {motor_id} is not connected. Please connect it before homing.")

            tasks = []
            max_position = 4_294_967_296

            for motor_id, device in self.devices.items():
                current_pos = self.read_motor_position(motor_id)
                if current_pos != 0:
                    target_pos = -current_pos if current_pos < 1_000_000 else max_position - current_pos
                    self.logger.info(f"Motor {motor_id} target position calculated as: {target_pos}")
                    tasks.append(self.move_motor_async(motor_id, target_pos))

            if not tasks:
                self.logger.info("All motors are already at their home position. No movement needed.")
                return

            # Execute tasks concurrently
            results = await asyncio.gather(*tasks)
            for motor_id, result in enumerate(results, start=1):
                self.logger.info(f"Motor {motor_id} move result: {result}")

            execution_time = time.time() - start_time
            self.logger.info(f"Homing process completed in {execution_time:.2f} seconds")

        except Exception as e:
            self.logger.error(f"Failed to home motors: {e}")
            raise


    def move_motor(self, motor_id, pos, vel=5):
        """
        Synchronously move the specified motor to a target position 
        at a given velocity in Profile Position mode.

        Parameters
        ----------
        motor_id : int
            The identifier of the motor to be moved.
        pos : int
            The target position for the motor.
        vel : int, optional
            The velocity for the movement (default is 5).

        Returns
        -------
        dict
            A dictionary containing the initial and final positions, 
            position change, and execution time of the movement.

        Raises
        ------
        Exception
            If the motor is not connected or an error occurs during movement.
        """
        self.logger.debug(f"Moving Motor {motor_id} to position {pos} with velocity {vel}")
        device = self.devices.get(motor_id)

        if not device or not device["connected"]:
            raise Exception(f"Error: Motor {motor_id} is not connected. Please connect it before moving.")

        try:
            device_handle = device["handle"]
            start_time = time.time()

            # Set Profile Position mode
            self.nanolib_accessor.writeNumber(device_handle, 1, Nanolib.OdIndex(0x6060, 0x00), 8)

            # Set velocity and target position
            self.nanolib_accessor.writeNumber(device_handle, vel, Nanolib.OdIndex(0x6081, 0x00), 32)
            initial_position = self.read_motor_position(motor_id)
            self.nanolib_accessor.writeNumber(device_handle, pos, Nanolib.OdIndex(0x607A, 0x00), 32)

            # Enable and execute movement
            for command in [6, 7, 0xF]:
                self.nanolib_accessor.writeNumber(device_handle, command, Nanolib.OdIndex(0x6040, 0x00), 16)
            self.nanolib_accessor.writeNumber(device_handle, 0x5F, Nanolib.OdIndex(0x6040, 0x00), 16)

            # Wait for movement completion
            while True:
                status_word = self.nanolib_accessor.readNumber(device_handle, Nanolib.OdIndex(0x6041, 0x00))
                if (status_word.getResult() & 0x1400) == 0x1400:
                    break
                time.sleep(0.1)

            final_position = self.read_motor_position(motor_id)
            return {
                "initial_position": initial_position,
                "final_position": final_position,
                "position_change": final_position - initial_position,
                "execution_time": time.time() - start_time,
            }

        except Exception as e:
            self.logger.error(f"Failed to move Motor {motor_id}: {e}")
            raise



    def read_motor_position(self, motor_id: int) -> int:
        """
        Read and return the current position of the specified motor.

        Parameters
        ----------
        motor_id : int
            The identifier of the motor.

        Returns
        -------
        int
            The current position of the motor.

        Raises
        ------
        Exception
            If the motor is not connected or an error occurs while reading 
            the position.
        """
        device = self.devices.get(motor_id)
        if not device or not device["connected"]:
            raise Exception(f"Error: Motor {motor_id} is not connected. Please connect it before reading the position.")

        try:
            device_handle = device["handle"]
            position_result = self.nanolib_accessor.readNumber(device_handle, Nanolib.OdIndex(0x6064, 0x00))
            if position_result.hasError():
                raise Exception(f"Error: readNumber() - {position_result.getError()}")
            return position_result.getResult()

        except Exception as e:
            self.logger.error(f"Failed to read position for Motor {motor_id}: {e}")
            raise


    def device_state(self, motor_id=0):
        """
        Retrieve the state of the specified motor or both motors.

        Parameters
        ----------
        motor_id : int, optional
            The identifier of the motor (default is 0). Use:
            - 0 to check the state of both motors,
            - 1 for motor 1,
            - 2 for motor 2.

        Returns
        -------
        dict
            A dictionary containing the connection states of the motors.

        Raises
        ------
        ValueError
            If an invalid motor number is provided.
        """
        if motor_id not in [0, 1, 2]:
            raise ValueError("Invalid motor number. Use 0 for both motors, 1 for motor 1, or 2 for motor 2.")

        res = {}
        motors = [motor_id] if motor_id in [1, 2] else [1, 2]
        for motor in motors:
            device = self.devices.get(motor)
            if device and device["handle"]:
                connection_state = self.nanolib_accessor.checkConnectionState(device["handle"]).getResult()
                res[f"motor{motor}"] = {"connection_state": bool(connection_state)}

        self.logger.info(f"Device states: {res}")
        return res


class ScanBusCallback(Nanolib.NlcScanBusCallback):
    """
    Callback class for handling bus scanning progress and results.
    """

    def __init__(self):
        super().__init__()

    def callback(self, info, devicesFound, data):
        """
        Handles scanning events.

        Parameters
        ----------
        info : Nanolib.BusScanInfo
            Information about the current scan state.
        devicesFound : int
            The number of devices found during the scan.
        data : int
            Additional data relevant to the scan event.

        Returns
        -------
        Nanolib.ResultVoid
            The result indicating the callback execution.
        """
        if info == Nanolib.BusScanInfo_Start:
            print('Scan started.')
        elif info == Nanolib.BusScanInfo_Progress:
            if (data & 1) == 0:
                print('.', end='', flush=True)
        elif info == Nanolib.BusScanInfo_Finished:
            print('\nScan finished.')

        return Nanolib.ResultVoid()

callbackScanBus = ScanBusCallback() # Nanolib 2021