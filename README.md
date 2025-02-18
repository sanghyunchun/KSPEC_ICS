# KSPECICS
The `KSPEC_ICS` is a Python-based application to send command message to relevent instruments of KSPEC,such as GFA, ADC, SPECTROGRAPH, and etc, via RabbitMQ message broker.
In addition, the `KSPEC_ICS` can run a server that enables each instrument to operate.



## Installaction
To install the `KSPEC_ICS', clone the repository and check package path

```bash
git clone https://github.com/sanghyunchun/KSPEC_ICS.git
```

In ADC/kspec_adc_controller/src/adc_actions.py, check the imported package path

```python
from .adc_controller import AdcController
from .adc_logger import AdcLogger
from .adc_calc_angle import ADCCalc
```

In ADC/kspec_adc_controller/src/adc_calc_angle.py, check the path of lookup_table

```python
def __init__(self, logger, lookup_table="./ADC/kspec_adc_controller/src/etc/ADC_lookup.csv", method="pchip"):
        self.logger = logger
        self.create_interp_func(lookup_table, method)
```

In ADC/kspec_adc_controller/src/adc_controller.py, check the path of config.json file

```python
CONFIG_FILE = "./ADC/kspec_adc_controller/src/etc/adc_config.json"
```

In GFA/kspec_gfa_controller/src/gfa_actions.py, check the imported package path

```python
from .gfa_logger import GFALogger
from .gfa_controller import GFAController
from .gfa_astrometry import GFAAstrometry
from .gfa_guider import GFAGuider
```



## Usage Examples
Here is a basic example to run ics and other instrument server.

### Run ICS program.

```bash
 python KSPECRUN.py ics
```

The following message must be displayed without fail.
```
RabbitMQ server connected
ics.ex exchange was defined

Input command:
```


### Run each instrument server
Use abbreviation of instrument 
```bash
python KSPECRUN.py ADC

python KSPECRUN.py GFA
```

Depending on instrument, the message displayed varies, but
is roughly similar to the following.

```bash
GFA Sever Started!!!
RabbitMQ server connected
Waiting for message from client......
```

Check for error messagees, and ensure that the phrase
"waiting for message from client...." appears as the end.
