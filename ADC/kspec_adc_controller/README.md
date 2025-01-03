
# KSPEC ADC Controller

The `kspec_adc_controller` is a Python-based application designed to interface with the K-SPEC ADC, enabling precise atmospheric dispersion correction during KSPEC observations. This tool is designed for astronomers and engineers working with the KSPEC instrument.

## Features

### Atmospheric Dispersion Correction
The K-SPEC ADC corrects for atmospheric dispersion during astronomical observations. By controlling two prism motors, the ADC performs variable counter-dispersion to compensate for dispersion caused by observing at different zenith angles (Wehbe et al., 2019).

### Key Functions
- **`Activate()`**: Engages the ADC system, allowing dynamic adjustments during observations.

## Installation

To install the `kspec_adc_controller`, clone the repository and install the required dependencies:

```bash
git clone https://github.com/mmingyeong/kspec_adc_controller.git
cd kspec_adc_controller
pip install -r requirements.txt
```

## Dependencies

- Python 3.6 or higher
- [Nanotec's NanoLib Python library](https://www.nanotec.com/eu/en/products/9985-nanolib)  
  Ensure that the NanoLib library is installed and properly configured to facilitate communication with the ADC hardware.
- Compatible hardware: K-SPEC ADC and prism motors system.

## Usage Example

Here is a basic example of using the Actions class for controlling the ADC:

```python
from kspec_adc_controller import AdcActions

# Initialize the Actions class
actions = AdcActions()

# Activate the ADC for dispersion correction
zenith_angle = 10
await actions.activate(zenith_angle)
```

## References

- Wehbe, C., et al. (2019). *Title of the Reference*. Journal Name, Volume(Issue), Page Numbers. DOI/Link.
