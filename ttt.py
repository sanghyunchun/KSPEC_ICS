class KSPECRunner:
    def __init__(self):
        """
        Initializes the KSPEC runner with the ICS client and network clients.
        """
        self.command_list = {
            "adc": ["adcstatus", "adcactivate", "adcadjust", "adcinit"],
            "gfa": ["gfastatus", "gfagrab", "gfastop", "gfaguide"],
            "fbp": ["fbpstatus", "fbpzero", "fbpmove", "fbpoffset"],
            "endo": ["endoguide", "endotest", "endofocus", "endostop"],
            "mtl": ["mtlstatus", "mtlexp", "mtlcal"],
            "lamp": ["lampstatus", "arcon", "arcoff", "flaton", "flatoff"],
            "spec": ["specstatus", "illuon", "illuoff", "getobj", "getbias"]
        }

    def find_category(self,cmd):
        for category, commands in self.command_list.items():
            print(commands)
#            if cmd in commands:
#                return category
#            return None
        





kkk=KSPECRunner()


cat=kkk.find_category('illuon')
print(cat)
