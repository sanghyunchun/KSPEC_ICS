import json


with open('./Lib/KSPEC.ini','r') as fs:
    kspecinfo=json.load(fs)

processini = kspecinfo['processini']
processfile = kspecinfo['processfile']

def initial():
    with open(processini,'r') as f:
        initial_status=json.load(f)
    f.close()

    with open(processfile,'r') as f:
        process_status=json.load(f)
    f.close()

    process_status.update(initial_status)

    with open(processfile,'w') as f:
        json.dump(process_status,f)

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
