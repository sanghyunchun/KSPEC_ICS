#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Mingyeong Yang (mmingyeong@kasi.re.kr)
# @Date: 2024-12-04
# @Filename: adc_logger.py

import logging
import os

class AdcLogger:
    """
    A logging utility class for managing console and optional file logging with distinct levels.

    This class supports simultaneous logging to the console and, optionally, to a file.
    """

    _initialized_loggers = set()  # Class-level set to track initialized loggers

    def __init__(self, stream_level=logging.INFO, enable_file_logging=False):
        """
        Initialize the logger with configurable log levels and optional file logging.

        Parameters
        ----------
        stream_level : int, optional
            Logging level for console output. Defaults to logging.DEBUG.
        enable_file_logging : bool, optional
            Whether to enable file logging. Defaults to False.
        """
        logger_name = os.path.basename(__file__)  # Use only the script filename
        if logger_name in AdcLogger._initialized_loggers:
            return
        AdcLogger._initialized_loggers.add(logger_name)

        # Create logger
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(logging.INFO)

        # Configure formatter
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"
        )

        # Console handler
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(logging.INFO)  # Set to DEBUG or INFO
        if not self.logger.hasHandlers():
            self.logger.addHandler(stream_handler)

        # Optional file handler
        if enable_file_logging:
            default_file_name = f"{logger_name}.log"
            file_handler = logging.FileHandler(default_file_name)
            file_handler.setFormatter(formatter)
            file_handler.setLevel(logging.DEBUG)  # Default file logging level
            self.logger.addHandler(file_handler)

    def debug(self, message):
        """Log a debug message."""
        self.logger.debug(message)

    def info(self, message):
        """Log an informational message."""
        self.logger.info(message)

    def warning(self, message):
        """Log a warning message."""
        self.logger.warning(message)

    def error(self, message):
        """Log an error message."""
        self.logger.error(message)