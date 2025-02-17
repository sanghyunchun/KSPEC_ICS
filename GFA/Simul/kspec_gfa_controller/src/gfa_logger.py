#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Mingyeong Yang (mmingyeong@kasi.re.kr)
# @Date: 2023-12-07
# @Filename: gfa_logger.py

import logging
import os
from datetime import datetime
from typing import Set

__all__ = ["GFALogger"]


class GFALogger:
    """
    A custom logging system for the GFA project that initializes both
    console (stream) and file handlers, storing logs in a 'log/' folder
    relative to this Python file.

    This class prevents multiple handlers from being added to the same
    logger by tracking initialized loggers in a class-level set.

    Attributes
    ----------
    file_name : str
        The base filename for which the logger is created.
    logger : logging.Logger
        The underlying logger instance.
    """

    _initialized_loggers: Set[str] = set()
    """
    A class-level set used to track which loggers have already been initialized.
    Prevents adding duplicate handlers for the same file_name.
    """

    def __init__(
        self,
        file: str,
        stream_level: int = logging.INFO,
        log_dir: str = None
    ) -> None:
        """
        Initialize a logger with a console (stream) handler and a file handler.
        Log files are placed in the `log/` directory, relative to this script.

        Parameters
        ----------
        file : str
            The file path/name used to derive this logger's identity.
        stream_level : int, optional
            The logging level for console output (default is logging.DEBUG).
        log_dir : str, optional
            If provided, overrides the default 'log/' folder. Otherwise,
            logs go to '<this_script_dir>/log/'.
        """
        # Determine the default log directory based on the current script location
        script_dir = os.path.dirname(os.path.abspath(__file__))
        if log_dir is None:
            log_dir = os.path.join(script_dir, "log")

        self.file_name = os.path.basename(file)
        self.logger = logging.getLogger(self.file_name)

        # If logger is already initialized, avoid adding duplicate handlers
        if self.file_name in GFALogger._initialized_loggers:
            return

        self.logger.setLevel(logging.INFO)  # Capture all messages >= INFO

        # Ensure the log directory exists
        os.makedirs(log_dir, exist_ok=True)

        # Create date-based log file path
        log_filename = f"gfa_{datetime.now().strftime('%Y-%m-%d')}.log"
        log_file_path = os.path.join(log_dir, log_filename)

        # Define a basic formatter
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

        # Stream (console) handler
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(stream_level)
        self.logger.addHandler(stream_handler)

        # File handler
        file_handler = logging.FileHandler(log_file_path, mode="a", encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)
        self.logger.addHandler(file_handler)

        # Mark this logger name as initialized
        GFALogger._initialized_loggers.add(self.file_name)

    def info(self, message: str) -> None:
        """
        Log an INFO-level message.

        Parameters
        ----------
        message : str
            The message to be logged.
        """
        self.logger.info(f"{message} (at {self.file_name})")

    def debug(self, message: str) -> None:
        """
        Log a DEBUG-level message.

        Parameters
        ----------
        message : str
            The message to be logged.
        """
        self.logger.debug(f"{message} (at {self.file_name})")

    def warning(self, message: str) -> None:
        """
        Log a WARNING-level message.

        Parameters
        ----------
        message : str
            The message to be logged.
        """
        self.logger.warning(f"{message} (at {self.file_name})")

    def error(self, message: str) -> None:
        """
        Log an ERROR-level message.

        Parameters
        ----------
        message : str
            The message to be logged.
        """
        self.logger.error(f"{message} (at {self.file_name})")
