import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
from TCS.tcstelcomp import Telcomclass

telcom=Telcomclass()
telcom.TelcomConnect()

def telcom_getra():
    """
    Connect the ADC instrument.

    Returns:
        str: JSON string containing the ADC connection command.
    """
    result=telcom.RequestRA()
    print(result.decode())
    return result.decode()

telcom.TelcomDisconnect()

