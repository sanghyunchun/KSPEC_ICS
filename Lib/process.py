import json
import shutil

processini = "./Lib/process.ini"
processfile = "./PROCESS/process.json"

def initial():
    shutil.copy2(processini,processfile)
    print('Process status is initialized')

    with open(processfile,'r') as f:
        process_status=json.load(f)
    f.close()

def update_process(inst,status):
    with open(processfile,'r') as f:
        process_status=json.load(f)

    f.close()

    process_update={inst+'process': status}

    process_status.update(process_update)

    with open(processfile,'w') as f:
        json.dump(process_status,f)

    f.close()

def get_process(inst):
    with open(processfile,'r') as f:
        process_status=json.load(f)

    f.close()
    prostat=process_status[inst+'process']
    return prostat
