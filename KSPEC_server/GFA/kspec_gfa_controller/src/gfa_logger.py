#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Mingyeong Yang (mmingyeong@kasi.re.kr)
# @Date: 2023-12-07
# @Filename: gfa_log.py

import logging
import os

__all__ = ["gfa_logger"]

class gfa_logger:
    """
    Custom logging system for the GFA project.

    Parameters
    ----------
    file : str
        The name of the file that will be used to create the logger.
        The log file will be named based on this parameter.
    """

    def __init__(self, file):
        """
        Initializes the logger with both stream and file handlers.

        Parameters
        ----------
        file : str
            The name of the file that will be used to create the logger.
        """
        self.logger = logging.getLogger("gfa_logger")
        self.file_name = os.path.basename(file)
        self.logger.setLevel(logging.DEBUG)  # Adjust log level as needed

        # StreamHandler for console output
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(
            logging.INFO
        )  # Set the logging level for the console output
        self.logger.addHandler(stream_handler)

        # FileHandler for writing logs to a file
        log_directory = "./src/log"
        os.makedirs(log_directory, exist_ok=True)  # Ensure the log directory exists
        log_name = self.file_name.rstrip(".py")
        file_handler = logging.FileHandler(
            os.path.join(log_directory, f"{log_name}.log")
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(
            logging.DEBUG
        )  # Set the logging level for the file output
        self.logger.addHandler(file_handler)

    def info(self, message):
        """
        Log an INFO level message.

        Parameters
        ----------
        message : str
            The message to log.
        """
        self.logger.info(f"{message} (at {self.file_name})")

    def debug(self, message):
        """
        Log a DEBUG level message.

        Parameters
        ----------
        message : str
            The message to log.
        """
        self.logger.debug(f"{message} (at {self.file_name})")

    def warning(self, message):
        """
        Log a WARNING level message.

        Parameters
        ----------
        message : str
            The message to log.
        """
        self.logger.warning(f"{message} (at {self.file_name})")

    def error(self, message):
        """
        Log an ERROR level message.

        Parameters
        ----------
        message : str
            The message to log.
        """
        self.logger.error(f"{message} (at {self.file_name})")
