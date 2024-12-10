import json


def initial():
    filepath='../Lib/process.ini'
    with open(filepath,'r') as f:
        initial_status=json.load(f)
    f.close()

    filepath='./PROCESS/process.json'
    with open(filepath,'r') as f:
        process_status=json.load(f)
    f.close()

    process_status.update(initial_status)

    with open(filepath,'w') as f:
        json.dump(process_status,f)

    f.close()

def update_process(inst,status):
    filepath='./PROCESS/process.json'
    with open(filepath,'r') as f:
        process_status=json.load(f)

    f.close()

    process_update={inst+'process': status}

    process_status.update(process_update)

    with open(filepath,'w') as f:
        json.dump(process_status,f)

    f.close()

def get_process(inst):
    filepath='./PROCESS/process.json'
    with open(filepath,'r') as f:
        process_status=json.load(f)

    f.close()
    prostat=process_status[inst+'process']
    return prostat
