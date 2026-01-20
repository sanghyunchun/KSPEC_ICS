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

    def __init__(self):
        """
        Initialize the AdcActions class and set up the ADC controller.

        Parameters
        ----------
        logger : AdcLogger, optional
            Logger instance for logging operations. If None, a default AdcLogger instance is created.
        """
        self.logger = AdcLogger(__file__)  # Use provided logger or create a default one
        self.logger.debug("Initializing AdcActions class.")
        self.controller = AdcController()
        self.controller.find_devices()
        self.calculator = ADCCalc()  # Method change line

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
            self.logger.error(f"Error in connect: {e}")
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
            return self._generate_response(
                "success", f"Motor {motor_num} status retrieved: {state}"
            )
        except Exception as e:
            self.logger.error(f"Error in status: {e}")
            return self._generate_response(
                "error", f"Error retrieving motor {motor_num} status: {str(e)}"
            )

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
            A response dictionary indicating the success or failure of the operation.
        """
        try:
            if motor_id == 0:
                self.logger.debug(
                    f"Starting simultaneous move for motors 1 and 2 to position {pos_count} with velocity {vel_set}."
                )

                motor1_task = asyncio.to_thread(
                    self.controller.move_motor, 1, -pos_count, vel_set
                )
                motor2_task = asyncio.to_thread(
                    self.controller.move_motor, 2, -pos_count, vel_set
                )

                # Wait for both motors to complete
                results = await asyncio.gather(motor1_task, motor2_task)

                self.logger.info("Both motors moved successfully.")
                return self._generate_response(
                    "success",
                    f"Both motors moved to position {pos_count} with velocity {vel_set}. ",
                    motor_1=results[0],
                    motor_2=results[1],
                )
            elif motor_id == -1:
                self.logger.debug(
                    f"Starting simultaneous move for motors 1 and 2 to position {pos_count} with velocity {vel_set} in same direction"
                )

                motor1_task = asyncio.to_thread(
                    self.controller.move_motor, 1, -pos_count, vel_set
                )
                motor2_task = asyncio.to_thread(
                    self.controller.move_motor, 2, pos_count, vel_set
                )

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
                result = await asyncio.to_thread(
                    self.controller.move_motor, motor_id, -pos_count, vel_set
                )
                self.logger.info(
                    f"Motor {motor_id} moved successfully to position {pos_count}."
                )
                return self._generate_response(
                    "success",
                    f"Motor {motor_id} moved to position {pos_count} with velocity {vel_set}. Result: {result}",
                )
        except Exception as e:
            self.logger.error(
                f"Error moving motor {motor_id} to position {pos_count} with velocity {vel_set}: {e}"
            )
            return self._generate_response(
                "error",
                f"Failed to move motor {motor_id} to position {pos_count} with velocity {vel_set}: {str(e)}",
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
            A response dictionary indicating success or failure of the operation.
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
                    f"Both motors stopped successfully. Results: Motor1: {results[0]}, Motor2: {results[1]}",
                )
            elif motor_id in [1, 2]:
                self.logger.debug(f"Stopping motor {motor_id}.")
                result = await asyncio.to_thread(self.controller.stop_motor, motor_id)
                self.logger.info(f"Motor {motor_id} stopped successfully.")
                return self._generate_response(
                    "success",
                    f"Motor {motor_id} stopped successfully. Result: {result}",
                )
            else:
                raise ValueError(f"Invalid motor ID: {motor_id}")
        except Exception as e:
            self.logger.error(f"Error stopping motor {motor_id}: {e}")
            return self._generate_response(
                "error", f"Failed to stop motor {motor_id}: {str(e)}"
            )

    async def activate(self, za, vel_set=1) -> dict:
        """
        Activate both motors simultaneously to the calculated target position based on zenith angle.

        Parameters
        ----------
        za : float
            Input zenith angle (in degrees) that determines the target position for the motors.
        vel_set : int, optional
            The velocity at which to move the motors (in RPM). Defaults to 1.
            Maximum allowed velocity is 5 RPM. If a value greater than 5 is provided,
            it will be automatically capped at 5 RPM.
            If a negative value is provided, it will be reset to the default value of 1 RPM.

        Returns
        -------
        dict
            A dictionary indicating the success or failure of the activation.
        """
        max_velocity = 5
        default_velocity = 1

        # Validate velocity
        if vel_set < 0:
            self.logger.warning(
                f"Requested velocity ({vel_set} RPM) is negative. "
                f"Setting velocity to the default value of {default_velocity} RPM."
            )
            vel = default_velocity
        else:
            vel = min(vel_set, max_velocity)
            if vel_set > max_velocity:
                self.logger.warning(
                    f"Requested velocity ({vel_set} RPM) exceeds the limit of {max_velocity} RPM. "
                    f"Setting velocity to {max_velocity} RPM."
                )

        self.logger.info(
            f"Activating motors with zenith angle {za}, velocity {vel} RPM."
        )

        try:
            # Calculate angle and position
            ang = self.calculator.calc_from_za(za)
            pos = self.calculator.degree_to_count(ang)
            self.logger.info(f"Calculated angle: {ang}, position: {pos}.")
        except Exception as e:
            self.logger.error(f"Error in calculating motor position: {e}")
            return self._generate_response(
                "error",
                f"Failed to calculate motor position for zenith angle {za}: {str(e)}",
            )

        try:
            # Activate motors
            # Activate motors using asyncio.to_thread for non-blocking calls
            # motor 1 L4 위치, 빛의 진행 방향 기준 시계 방향 회전
            motor1_task = asyncio.to_thread(self.controller.move_motor, 1, -pos, vel)
            # motor 2 L3 위치, 빛의 진행 방향 기준 반시계 방향 회전
            motor2_task = asyncio.to_thread(self.controller.move_motor, 2, -pos, vel)

            results = await asyncio.gather(
                motor1_task, motor2_task, return_exceptions=True
            )

            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    self.logger.error(f"Motor {i + 1} failed: {result}")
                    return self._generate_response(
                        "error",
                        f"Motor {i + 1} activation failed with position {pos} and velocity {vel}. Error: {result}",
                    )

            self.logger.info("Motors activated successfully.")
            return self._generate_response(
                "success",
                f"Motors activated to position {pos} with velocity {vel}. "
                f"Results: Motor1: {results[0]}, Motor2: {results[1]}",
            )
        except Exception as e:
            self.logger.error(f"Failed to activate motors with zenith angle {za}: {e}")
            return self._generate_response(
                "error",
                f"Failed to activate motors for zenith angle {za} with velocity {vel}: {str(e)}",
            )

    async def homing(self, homing_vel=1):
        """
        Perform a homing operation with the motor controller.
        """

        max_velocity = 5
        default_velocity = 1

        # Validate velocity
        if homing_vel < 0:
            self.logger.warning(
                f"Requested velocity ({homing_vel} RPM) is negative. "
                f"Setting velocity to the default value of {default_velocity} RPM."
            )
            vel = default_velocity
        else:
            vel = min(homing_vel, max_velocity)
            if homing_vel > max_velocity:
                self.logger.warning(
                    f"Requested velocity ({homing_vel} RPM) exceeds the limit of {max_velocity} RPM. "
                    f"Setting velocity to {max_velocity} RPM."
                )

        self.logger.info("Starting homing operation.")
        try:
            self.logger.debug("Calling homing method on controller.")
            await self.controller.homing(vel)

            state = self.controller.device_state(0)

            motor1_pos = state["motor1"]["position_state"]
            motor2_pos = state["motor2"]["position_state"]

            self.logger.info("Homing completed successfully.")
            return self._generate_response(
                "success",
                "Homing completed successfully.",
                motor_1=motor1_pos,
                motor_2=motor2_pos,
            )

        except Exception as e:
            self.logger.error(f"Error in homing operation: {str(e)}")
            return self._generate_response("error", str(e))

    async def parking(self, parking_vel=1):
        """
        Park the motors at a predefined position.

        This operation moves the motors to a predefined 'parking' position, which is usually a safe position
        where the motors are not obstructing any other devices or in a position where they can be safely powered off.

        Parameters
        ----------
        parking_vel : int, optional
            The velocity at which to move the motors (in RPM). Defaults to 1.
            Maximum allowed velocity is 5 RPM. If a value greater than 5 is provided,
            it will be automatically capped at 5 RPM.
            If a negative value is provided, it will be reset to the default value of 1 RPM.

        Returns
        -------
        dict
            A JSON-like dictionary indicating the success or failure of the operation:
            - "status": "success" if the parking operation was successful, "error" if it failed.
            - "message": A string explaining the failure, only present if "status" is "error".
        """

        max_velocity = 5
        default_velocity = 1

        # Validate velocity
        if parking_vel < 0:
            self.logger.warning(
                f"Requested velocity ({parking_vel} RPM) is negative. "
                f"Setting velocity to the default value of {default_velocity} RPM."
            )
            vel = default_velocity
        else:
            vel = min(parking_vel, max_velocity)
            if parking_vel > max_velocity:
                self.logger.warning(
                    f"Requested velocity ({parking_vel} RPM) exceeds the limit of {max_velocity} RPM. "
                    f"Setting velocity to {max_velocity} RPM."
                )

        self.logger.info("Starting parking operation.")
        try:
            self.logger.debug("Parking motors at predefined position.")
            await self.controller.parking(vel)
            self.logger.info("Parking completed successfully.")
            return self._generate_response("success", "Parking completed successfully.")
        except Exception as e:
            self.logger.error(f"Error in parking operation: {str(e)}")
            return self._generate_response("error", str(e))

    async def zeroing(self, zeroing_vel=1):
        """
        Perform a zeroing operation by adjusting motor positions based on calibrated offsets.

        This operation sets the motor's position offsets (e.g., by moving motors by a fixed number of counts).
        This may be required to compensate for any drift or to set a baseline for further operations.

        Parameters
        ----------
        zeroing_vel : int, optional
            The velocity at which to move the motors (in RPM). Defaults to 1.
            Maximum allowed velocity is 5 RPM. If a value greater than 5 is provided,
            it will be automatically capped at 5 RPM.
            If a negative value is provided, it will be reset to the default value of 1 RPM.

        Returns
        -------
        dict
            A dictionary indicating the success or failure of the zeroing operation:
            - "status": "success" if the zeroing was successful, "error" if it failed.
            - "message": A string explaining the failure, only present if "status" is "error".
        """
        max_velocity = 5
        default_velocity = 1

        # Validate velocity input
        if zeroing_vel < 0:
            self.logger.warning(
                f"Requested velocity ({zeroing_vel} RPM) is negative. "
                f"Setting velocity to the default value of {default_velocity} RPM."
            )
            vel = default_velocity
        else:
            vel = min(zeroing_vel, max_velocity)
            if zeroing_vel > max_velocity:
                self.logger.warning(
                    f"Requested velocity ({zeroing_vel} RPM) exceeds the limit of {max_velocity} RPM. "
                    f"Setting velocity to {max_velocity} RPM."
                )

        self.logger.info(f"Starting zeroing operation with velocity {vel} RPM.")

        try:
            self.logger.debug("Initiating homing as part of zeroing.")
            # Assuming self.controller.zeroing(vel) handles motor movement logic.
            await self.controller.zeroing(vel)
            self.logger.info("Zeroing operation completed successfully.")
            return self._generate_response("success", "Zeroing completed successfully.")
        except Exception as e:
            self.logger.error(f"Error in zeroing operation: {str(e)}")
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
            self.logger.error(f"Error in disconnect: {str(e)}")
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
            return self._generate_response(
                "success", "Power off and devices disconnected."
            )
        except Exception as e:
            self.logger.error(f"Error in power off: {str(e)}")
            return self._generate_response("error", str(e))

    def calc_from_za(self, za) -> dict:
        """
        Calculate from ZA using the calculator object.

        This function computes a value from the provided ZA input using an internal calculator.

        Parameters
        ----------
        za : float
            ZA value to be converted.

        Returns
        -------
        dict
            A JSON-like dictionary indicating the success or failure of the operation:
            - "status": "success" if the operation was successful.
            - "message": The computed value.
        """
        self.logger.info("Calculating from ZA.")
        try:
            fn_za_adc = self.calculator.calc_from_za(za)
            self.logger.info(f"Calculation successful: {fn_za_adc}")
            return self._generate_response("success", fn_za_adc)
        except Exception as e:
            self.logger.error(f"Error calculating from ZA: {str(e)}")
            return self._generate_response("error", str(e))

    def degree_to_count(self, degree) -> dict:
        """
        Convert degrees to counts using the calculator object.

        This function converts an angle in degrees to encoder counts using an internal calculator.

        Parameters
        ----------
        degree : float
            Angle in degrees to be converted.

        Returns
        -------
        dict
            A JSON-like dictionary indicating the success or failure of the operation:
            - "status": "success" if the operation was successful.
            - "message": The computed value.
        """
        self.logger.info("Converting degrees to counts.")
        try:
            count = self.calculator.degree_to_count(degree)
            self.logger.info(f"Conversion successful: {count}")
            return self._generate_response("success", count)
        except Exception as e:
            self.logger.error(f"Error converting degrees to counts: {str(e)}")
            return self._generate_response("error", str(e))
