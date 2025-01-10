#!/usr/bin/env python
# -*- coding: utf-8 -*- 
#
# @Author: Mingyeong Yang (mmingyeong@kasi.re.kr)
# @Date: 2024-06-26
# @Filename: adc_actions.py

import asyncio
from .adc_controller import AdcController
from .adc_logger import AdcLogger
from .adc_calc_angle import ADCCalc

__all__ = ["AdcActions"]

class AdcActions:
    """Class to manage ADC actions including connecting, powering on/off, and motor control."""

    def __init__(self, logger=None):
        """
        Initialize the AdcActions class and set up the ADC controller.

        Parameters
        ----------
        logger : AdcLogger, optional
            Logger instance for logging operations. If None, a default AdcLogger instance is created.
        """
        self.logger = logger or AdcLogger(__file__)  # Use provided logger or create a default one
        self.logger.debug("Initializing AdcActions class.")
        self.controller = AdcController(self.logger)
        self.controller.find_devices()
        self.calculator = ADCCalc(self.logger)  # Method change line

    def connect(self):
        """
        Connect to the ADC controller.

        Returns
        -------
        dict
            A dictionary indicating the success or failure of the operation.
        """
        self.logger.info("Connecting to devices.")
        try:
            self.controller.connect()
            self.logger.info("Connection successful.")
            return self._generate_response("success", "Connected to devices.")
        except Exception as e:
            self.logger.error(f"Error in connect: {e}", exc_info=True)
            return self._generate_response("error", f"Failed to connect: {str(e)}")

    def _generate_response(self, status: str, message: str, **kwargs) -> dict:
        """
        Generate a response dictionary.

        Parameters
        ----------
        status : str
            Status of the operation ('success' or 'error').
        message : str
            Message describing the operation result.
        **kwargs : dict
            Additional data to include in the response.

        Returns
        -------
        dict
            A dictionary representing the response.
        """
        # Ensure 'status' and 'message' are included in the response, and optionally update with additional data
        response = {"status": status, "message": message}
        response.update(kwargs)
        return response

    def status(self, motor_num: int = 0) -> dict:
        """
        Get the status of a specified motor.

        Parameters
        ----------
        motor_num : int, optional
            The motor number to check. Default is 0.

        Returns
        -------
        dict
            A dictionary indicating the status or any error encountered.
        """
        self.logger.info(f"Retrieving status for motor {motor_num}.")
        try:
            state = self.controller.device_state(motor_num)
            self.logger.info(f"Motor {motor_num} status: {state}")
            return self._generate_response("success", f"Motor {motor_num} status retrieved.", DeviceState=state)
        except Exception as e:
            self.logger.error(f"Error in status: {e}", exc_info=True)
            return self._generate_response("error", f"Error retrieving motor {motor_num} status: {str(e)}", motor_num=motor_num)


    async def move(self, motor_id, pos_count, vel_set=1):
        """
        Move the motor(s) to the specified position with a given velocity.
        
        Parameters
        ----------
        motor_id : int
            The motor ID to move. If `0`, both motors 1 and 2 will be moved simultaneously.
        pos_count : int
            The target position to move the motor(s) to.
        vel_set : int, optional
            The velocity at which to move the motor(s). Defaults to 1.
        
        Returns
        -------
        dict
            A response dictionary indicating the success or failure of the operation, 
            including the results of the motor movement.
        """
        try:
            if motor_id == 0:
                self.logger.debug(
                    f"Starting simultaneous move for motors 1 and 2 to position {pos_count} with velocity {vel_set}."
                )

                motor1_task = asyncio.to_thread(self.controller.move_motor, 1, pos_count, vel_set)
                motor2_task = asyncio.to_thread(self.controller.move_motor, 2, pos_count, vel_set)

                # Wait for both motors to complete
                results = await asyncio.gather(motor1_task, motor2_task)

                self.logger.info("Both motors moved successfully.")
                return self._generate_response(
                    "success",
                    "Both motors activated successfully.",
                    motor_1=results[0],
                    motor_2=results[1],
                )
            else:
                self.logger.debug(
                    f"Moving motor {motor_id} to position {pos_count} with velocity {vel_set}."
                )
                result = await asyncio.to_thread(self.controller.move_motor, motor_id, pos_count, vel_set)
                self.logger.info(f"Motor {motor_id} moved successfully to position {pos_count}.")
                return self._generate_response(
                    "success",
                    f"Motor {motor_id} activated successfully.",
                    result=result,
                )
        except Exception as e:
            self.logger.error(f"Error moving motor {motor_id} to position {pos_count} with velocity {vel_set}: {e}", exc_info=True)
            return self._generate_response(
                "error", 
                f"Error activating motor {motor_id}.", 
                error=str(e),
            )

    async def stop(self, motor_id):
        """
        Stop the specified motor(s). If motor_id is 0, both motors 1 and 2 are stopped simultaneously.

        Parameters
        ----------
        motor_id : int
            The motor ID to stop. If `0`, both motors 1 and 2 will be stopped simultaneously.

        Returns
        -------
        dict
            A response dictionary indicating success or failure of the operation, 
            including the results of stopping the motor(s).
        """
        try:
            if motor_id == 0:
                self.logger.debug("Stopping both motors simultaneously.")
                motor1_task = asyncio.to_thread(self.controller.stop_motor, 1)
                motor2_task = asyncio.to_thread(self.controller.stop_motor, 2)
                results = await asyncio.gather(motor1_task, motor2_task)
                self.logger.info("Both motors stopped successfully.")
                return self._generate_response(
                    "success",
                    "Both motors stopped successfully.",
                    motor_1=results[0],
                    motor_2=results[1],
                )
            elif motor_id in [1, 2]:
                self.logger.debug(f"Stopping motor {motor_id}.")
                result = await asyncio.to_thread(self.controller.stop_motor, motor_id)
                self.logger.info(f"Motor {motor_id} stopped successfully.")
                return self._generate_response(
                    "success",
                    f"Motor {motor_id} stopped successfully.",
                    result=result,
                )
            else:
                raise ValueError(f"Invalid motor ID: {motor_id}")
        except Exception as e:
            self.logger.error(f"Error stopping motor {motor_id}: {e}", exc_info=True)
            return self._generate_response(
                "error", 
                f"Error stopping motor {motor_id}.", 
                error=str(e),
            )

    async def activate(self, za, vel_set=1) -> dict:
        """
        Activate both motors simultaneously to the calculated target position based on zenith angle.

        Parameters
        ----------
        za : float
            Input zenith angle (in degrees) that determines the target position for the motors.
        vel_set : int, optional
            The velocity at which to move the motors. Defaults to 1.

        Returns
        -------
        dict
            A dictionary indicating the success or failure of the activation.
        """
        self.logger.info(f"Activating motors with zenith angle {za}.")
        vel = vel_set  # default velocity

        ang = self.calculator.calc_from_za(za)
        pos = self.calculator.degree_to_count(ang)

        try:
            # Activate motors using asyncio.to_thread for non-blocking calls
            motor1_task = asyncio.to_thread(self.controller.move_motor, 1, -pos, vel)  # motor 1 L4 위치, 시계 방향 회전
            motor2_task = asyncio.to_thread(self.controller.move_motor, 2, -pos, vel)  # motor 2 L3 위치, 반시계 방향 회전

            results = await asyncio.gather(motor1_task, motor2_task)

            self.logger.info("Motors activated successfully.")
            return self._generate_response(
                "success",
                "Motors activated successfully.",
                motor_1=results[0],
                motor_2=results[1],
            )
        except Exception as e:
            self.logger.error(f"Failed to activate motors with zenith angle {za}: {e}", exc_info=True)
            return self._generate_response(
                "error", 
                f"Error activating motors with zenith angle {za}.", 
                error=str(e),
            )


    async def homing(self):
        """
        Perform a homing operation with the motor controller.
        
        The homing operation attempts to move the motor to its home position. This is usually a predefined
        starting point or a limit switch where the motor is considered to be at its 'home' position.

        Returns
        -------
        dict
            A JSON-like dictionary with the operation's status. Contains:
            - "status": "success" if the homing operation was successful, "error" if it failed.
            - "message": A string explaining the failure, only present if "status" is "error".
        """
        self.logger.info("Starting homing operation.")
        try:
            self.logger.debug("Calling homing method on controller.")
            await self.controller.homing()
            self.logger.info("Homing completed successfully.")
            return self._generate_response("success", "Homing completed successfully.")
        except Exception as e:
            self.logger.error(f"Error in homing operation: {str(e)}", exc_info=True)
            return self._generate_response("error", str(e))

    async def zeroing(self):
        """
        Perform a zeroing operation by adjusting motor positions based on calibrated offsets.
        
        This operation sets the motor's position offsets (e.g., by moving motors by a fixed number of counts).
        This may be required to compensate for any drift or to set a baseline for further operations.

        Returns
        -------
        dict
            A JSON-like dictionary indicating the success or failure of the operation:
            - "status": "success" if the zeroing was successful, "error" if it failed.
            - "message": A string explaining the failure, only present if "status" is "error".
        """
        zero_offset_motor1 = 7500  # Adjust this value based on calibration.
        zero_offset_motor2 = 2000  # Adjust this value based on calibration.

        self.logger.info("Starting zeroing operation.")
        try:
            self.logger.debug("Initiating homing as part of zeroing.")
            await self.controller.homing()
            self.logger.debug(f"Moving motor 1 by {zero_offset_motor1} counts.")
            self.logger.debug(f"Moving motor 2 by {zero_offset_motor2} counts.")
            await asyncio.gather(
                asyncio.to_thread(self.controller.move_motor, 1, zero_offset_motor1, 5),
                asyncio.to_thread(self.controller.move_motor, 2, zero_offset_motor2, 5)
            )
            self.logger.info("Zeroing completed successfully.")
            return self._generate_response("success", "Zeroing completed successfully.")
        except Exception as e:
            self.logger.error(f"Error in zeroing operation: {str(e)}", exc_info=True)
            return self._generate_response("error", str(e))

    def disconnect(self):
        """
        Disconnect from the ADC controller and related devices.
        
        This function will disconnect any active connections to the motor controller or other connected devices.

        Returns
        -------
        dict
            A JSON-like dictionary indicating the success or failure of the operation:
            - "status": "success" if the disconnection was successful, "error" if it failed.
            - "message": A string explaining the failure, only present if "status" is "error".
        """
        self.logger.info("Disconnecting from devices.")
        try:
            self.controller.disconnect()
            self.logger.info("Disconnection successful.")
            return self._generate_response("success", "Disconnected from devices.")
        except Exception as e:
            self.logger.error(f"Error in disconnect: {str(e)}", exc_info=True)
            return self._generate_response("error", str(e))

    def power_off(self) -> dict:
        """
        Power off and disconnect from all devices, shutting down the system safely.

        This function will close all active connections and power off the system, ensuring no devices are left in an inconsistent state.

        Returns
        -------
        dict
            A JSON-like dictionary indicating the success or failure of the operation:
            - "status": "success" if the operation was successful, "error" if it failed.
            - "message": A string explaining the failure, only present if "status" is "error".
        """
        self.logger.info("Powering off and disconnecting from devices.")
        try:
            self.controller.disconnect()
            self.controller.close()
            self.logger.info("Power off successful.")
            return self._generate_response("success", "Power off and devices disconnected.")
        except Exception as e:
            self.logger.error(f"Error in power off: {str(e)}", exc_info=True)
            return self._generate_response("error", str(e))
