import os, sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
import Lib.mkmessage as mkmsg
from TCS import tcscli
import Lib.process as processes

processes.initial()
