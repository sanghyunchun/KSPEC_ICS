### v1.0.0 - Initial Release (2025-01-14)

- **New Features**:
  - **`adc_actions.py`**: Implemented core ADC operations, providing ADC configuration and data reading functionality.
  - **`adc_controller.py`**: Implemented communication and control with ADC hardware, including device initialization and status checks.
  - **Supporting modules**: Provided auxiliary files for signal processing and additional configuration.

- **Performance Improvements**:
  - Optimized ADC processing, improving real-time data collection and control function.
  
- **Bug Fixes**:
  - Fixed issues with initialization and communication with hardware.

- **Documentation**:
  - Documented installation and usage instructions, along with descriptions of key features and APIs.
  - Provided sample code and usage examples.


### v1.1.0 - Post-February Field Test Updates (2025-02-12)

- **New Features**:
  - **Velocity Limits**: Enforced motor speed limits (max **5 RPM**, default **1 RPM**) to prevent excessive speeds and ensure safe operation.
  - **Logging Enhancements**: Added detailed logging messages for motor movements, homing, parking, and zeroing processes, improving debugging and diagnostics.
  - **Error Handling**: Strengthened exception handling across motor control functions to reduce unexpected crashes and improve reliability.

- **Improvements**:
  - **Configuration Management**: Updated **ADC configuration file path** for better project structure and maintainability.
  - **Motor Position Adjustments**: Refined **zeroing, parking, and homing** calculations to ensure more accurate motor positioning based on field test feedback.
  - **Homing Process**: Improved homing logic with **bus stop validation** and **timeout protection**, preventing unnecessary movements.
  - **Motor Stop Logic**: Verified motor **halt status** using status word checks to confirm successful stopping before proceeding.

- **Bug Fixes**:
  - Resolved potential issues causing **unexpected motor movements** after homing or zeroing.
  - Fixed handling of **motor connection states**, ensuring correct device status reporting.


### v1.2.0 - Calculator Command Enhancements (2025-02-13)

- **New Features**:
  - **Calculator Commands**: Added `calc_from_za` and `degree_to_count` functions with complete docstrings, logging, and structured responses using `_generate_response()`.

- **Improvements**:
  - **Logging Enhancements**: Added detailed logging for calculation operations, ensuring clearer diagnostics during debugging.
  - **Response Consistency**: Unified success and error responses across all commands, aligning with `power_off` function standards.
  
- **Error Handling**:
  - Enhanced exception handling in `calc_from_za` and `degree_to_count` to log errors with stack traces and return standardized error responses.

### v1.2.1 - Absolute Path & Logging Improvements (2025-02-19)

- **New Features**:
  - **Default Config Lookups**: Introduced `_get_default_adc_config_path()` and `_get_default_lookup_path()` to dynamically determine the absolute path for ADC configs and lookup tables.
  
- **Improvements**:
  - **AdcController**: Uses absolute paths for config files, preventing file-not-found errors irrespective of where the script is executed.
  - **AdcCalc**: Employs `_get_default_lookup_path()` to load `ADC_lookup.csv` from a consistent, absolute directory reference.
  - **AdcLogger**: Enhanced logging behaviors to unify console and file outputs, ensuring logs are always written to the script’s directory regardless of runtime location.
  - **Response & Logging Consistency**: Standardized success/error handling across all modules, improving debuggability and clarity when exceptions occur.
  
- **Error Handling**:
  - **FileNotFoundError Enhancements**: Clear, immediate exceptions if config or lookup CSV files are missing or unreadable, aiding rapid issue identification.
  - **Detailed Stack Traces**: Errors in initialization or config loading now log full exception details, expediting troubleshooting.
