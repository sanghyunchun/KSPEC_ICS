#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Mingyeong Yang (mmingyeong@kasi.re.kr)
# @Date: 2024-06-26
# @Filename: adc_actions.py

import asyncio
from adc_controller import AdcController
from adc_logger import AdcLogger
from adc_calc_angle import ADCCalc

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
        self.logger = logger or AdcLogger(
            __file__
        )  # Use provided logger or create a default one
        self.logger.debug("Initializing AdcActions class.")
        self.controller = AdcController(self.logger)
        self.controller.find_devices()
        self.calculator = ADCCalc(self.logger) # method 변경 line

    def connect(self):
        """
        Connect to the ADC controller.

        Returns:
        -------
        str
            A JSON string indicating the success or failure of the operation.
        """
        self.logger.info("Connecting to devices.")
        response = {}
        try:
            self.controller.connect()
            response = {
                "status": "success",
                "message": "Connected to devices."
            }
            self.logger.info("Connection successful.")
        except Exception as e:
            self.logger.error(f"Error in connect: {str(e)}")
            response = {
                "status": "error",
                "message": str(e)
            }
        return response

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
                "success", f"Motor {motor_num} status retrieved.", DeviceState=state
            )
        except Exception as e:
            self.logger.error(f"Error in status: {e}")
            return self._generate_response("error", str(e), motor_num=motor_num)

    async def activate(self, pos, vel_set) -> dict:
        """
        Activate both motors simultaneously with specified velocities.

        Parameters
        ----------
        za_angle : float or array(float)
            Input zenith angle (degree)

        Returns
        -------
        dict
            A dictionary indicating the success or failure of the activation.
        """
#        self.logger.info(f"Activating motors. za_angle={za}")
        vel = vel_set  # deafault

#        ang = self.calculator.calc_from_za(za)
#        pos = self.calculator.degree_to_count(ang)

        try:
            #self.controller.connect()

            async def move_motor_async(motor_num, position, velocity):
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(
                    None, self.controller.move_motor, motor_num, position, velocity
                )

            motor1_task = move_motor_async(1, -pos, vel)
 #           motor2_task = move_motor_async(2, -pos, vel)

#            results = await asyncio.gather(motor1_task, motor2_task)
            results = await asyncio.gather(motor1_task)
#            results = await asyncio.gather(motor2_task)

            self.logger.info("Motors activated successfully.")
            return self._generate_response(
                "success",
                "Motors activated successfully.",
                motor_1=results[0],
#                motor_2=results[1],
            )
        except Exception as e:
            self.logger.error(f"Failed to activate motors: {e}")
            return self._generate_response("error", str(e))

    async def homing(self):
        """
        Perform homing operation with specified parameters.

        Returns:
        -------
        str
            A JSON string indicating the success or failure of the operation.
        """
        self.logger.info("Starting homing operation.")
        response = {}
        try:
            await self.controller.homing()
            response = {
                "status": "success",
                "message": "Homing completed.",
            }
            self.logger.info("Homing completed successfully.")
        except Exception as e:
            self.logger.error(f"Error in homing: {str(e)}")
            response = {
                "status": "error",
                "message": str(e),
            }
        return response

    def power_off(self) -> dict:
        """
        Power off and disconnect from all devices.

        Returns
        -------
        dict
            A dictionary indicating the success or failure of the operation.
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
            self.logger.error(f"Error in power off: {e}")
            return self._generate_response("error", str(e))


"""""" """
    def poweron(self):
        """ """
        Power on and connect to all devices.

        Returns:
        -------
        str
            A JSON string indicating the success or failure of the operation.
        """ """
        logging.info("Powering on and connecting to devices.")
        response = {}
        try:
            self.controller.find_devices()
            self.controller.connect()
            response = {
                "status": "success",
                "message": "Power on and devices connected."
            }
            logging.info("Power on successful.")
        except Exception as e:
            logging.error(f"Error in poweron: {str(e)}")
            response = {
                "status": "error",
                "message": str(e)
            }
        return json.dumps(response)

    def poweroff(self):
        """ """
        Power off and disconnect from all devices.

        Returns:
        -------
        str
            A JSON string indicating the success or failure of the operation.
        """ """
        logging.info("Powering off and disconnecting from devices.")
        response = {}
        try:
            self.controller.disconnect()
            self.controller.close()
            response = {
                "status": "success",
                "message": "Power off and devices disconnected."
            }
            logging.info("Power off successful.")
        except Exception as e:
            logging.error(f"Error in poweroff: {str(e)}")
            response = {
                "status": "error",
                "message": str(e)
            }
        return json.dumps(response)

    def connect(self):
        """ """
        Connect to the ADC controller.

        Returns:
        -------
        str
            A JSON string indicating the success or failure of the operation.
        """ """
        logging.info("Connecting to devices.")
        response = {}
        try:
            self.controller.connect()
            response = {
                "status": "success",
                "message": "Connected to devices."
            }
            logging.info("Connection successful.")
        except Exception as e:
            logging.error(f"Error in connect: {str(e)}")
            response = {
                "status": "error",
                "message": str(e)
            }
        return json.dumps(response)

    def disconnect(self):
        """ """
        Disconnect from the ADC controller.

        Returns:
        -------
        str
            A JSON string indicating the success or failure of the operation.
        """ """
        logging.info("Disconnecting from devices.")
        response = {}
        try:
            self.controller.disconnect()
            response = {
                "status": "success",
                "message": "Disconnected from devices."
            }
            logging.info("Disconnection successful.")
        except Exception as e:
            logging.error(f"Error in disconnect: {str(e)}")
            response = {
                "status": "error",
                "message": str(e)
            }
        return json.dumps(response)

    def status(self, motor_num=0):
        """ """
        Get the status of a specified motor.

        Parameters:
        ----------
        motor_num : int, optional
            The motor number to check. Default is 0.

        Returns:
        -------
        str
            A JSON string indicating the status or any error encountered.
        """ """
        logging.info(f"Retrieving status for motor {motor_num}.")
        response = {}
        try:
            state = self.controller.DeviceState(motor_num)
            response = {
                "status": "success",
                "message": f"Motor {motor_num} status retrieved.",
                "DeviceState": state
            }
            logging.info(f"Motor {motor_num} status: {state}")
        except Exception as e:
            logging.error(f"Error in status: {str(e)}")
            response = {
                "status": "error",
                "message": str(e),
                "motor_num": motor_num
            }
        return json.dumps(response)

    async def activate(self, pos:int, vel1=5, vel2=5):
        """ """
        #Activate both motors simultaneously with specified velocities.

        #Parameters:
        #----------
        #vel1 : int, optional
        #    The target velocity for motor 1. Default is 5.
        #vel2 : int, optional
        #    The target velocity for motor 2. Default is 5.

        #Returns:
        #-------
        #str
        #    A JSON string indicating the success or failure of the activation.
        """ """
        logging.info("Activating motors.")
        response = {}

        async def move_motor_async(MotorNum, pos, vel):
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self.controller.move_motor, MotorNum, pos, vel)

        try:
            motor1_task = move_motor_async(1, pos, vel1)
            motor2_task = move_motor_async(2, pos, vel2)

            results = await asyncio.gather(motor1_task, motor2_task)

            response = {
                "status": "success",
                "message": "Motors activated successfully.",
                "motor_1": results[0],
                "motor_2": results[1]
            }
            logging.info("Motors activated successfully.")
        except Exception as e:
            logging.error(f"Failed to activate motors: {str(e)}")
            response = {
                "status": "error",
                "message": str(e)
            }

        return json.dumps(response)

    async def homing(self):
        """ """
        #Perform homing operation with specified parameters.

        #Returns:
        #-------
        #str
        #    A JSON string indicating the success or failure of the operation.
        """ """
        logging.info("Starting homing operation.")
        response = {}
        try:
            state = await self.controller.homing()
            response = {
                "status": "success",
                "message": "Homing completed.",
            }
            logging.info("Homing completed successfully.")
        except Exception as e:
            logging.error(f"Error in homing: {str(e)}")
            response = {
                "status": "error",
                "message": str(e),
            }
        return json.dumps(response)
""" """"""
