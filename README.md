# KSPECICS
The `KSPEC_ICS` is a Python-based application to send command message to relevent instruments of KSPEC,such as GFA, ADC, SPECTROGRAPH, and etc, via RabbitMQ message broker.



## Installaction
To install the `KSPEC_ICS', clone the repository and check package path

```bash
git clone https://github.com/sanghyunchun/KSPEC_ICS.git
```

In ADC/kspec_adc_controller/src/adc_actions.py

```python
from .adc_controller import AdcController
from .adc_logger import AdcLogger
from .adc_calc_angle import ADCCalc
```

