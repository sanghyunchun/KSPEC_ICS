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
    stream_level : int, optional
        The logging level for the console (default is logging.INFO).
    file_level : int, optional
        The logging level for the file (default is logging.DEBUG).
    """

    _initialized_loggers = set()  # Class attribute to track initialized loggers

    def __init__(self, file, stream_level=logging.INFO, file_level=logging.DEBUG):
        """
        Initializes the logger with both stream and file handlers.

        Parameters
        ----------
        file : str
            The name of the file that will be used to create the logger.
        stream_level : int, optional
            The logging level for the console (default is logging.INFO).
        file_level : int, optional
            The logging level for the file (default is logging.DEBUG).
        """
        self.file_name = os.path.basename(file)
        self.logger = logging.getLogger(self.file_name)  # Unique logger per file
        
        if self.file_name in gfa_logger._initialized_loggers:
            # If the logger for this file has already been initialized, skip adding handlers
            return
        
        self.logger.setLevel(logging.DEBUG)  # Set the lowest level, handlers control specific output

        # StreamHandler for console output
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(stream_level)
        self.logger.addHandler(stream_handler)

        # FileHandler for writing logs to a file
        log_directory = "/opt/kspec_gfa_controller/log"
        os.makedirs(log_directory, exist_ok=True)  # Ensure the log directory exists
        log_name = self.file_name.rstrip(".py")
        file_handler = logging.FileHandler(
            os.path.join(log_directory, f"{log_name}.log")
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(file_level)
        self.logger.addHandler(file_handler)

        # Mark this logger as initialized
        gfa_logger._initialized_loggers.add(self.file_name)

    def info(self, message):
        """Log an INFO level message."""
        self.logger.info(f"{message} (at {self.file_name})")

    def debug(self, message):
        """Log a DEBUG level message."""
        self.logger.debug(f"{message} (at {self.file_name})")

    def warning(self, message):
        """Log a WARNING level message."""
        self.logger.warning(f"{message} (at {self.file_name})")

    def error(self, message):
        """Log an ERROR level message."""
        self.logger.error(f"{message} (at {self.file_name})")
