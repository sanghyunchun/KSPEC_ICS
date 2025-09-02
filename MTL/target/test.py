import json

with open('MTLresult.json','r') as fs:
        alpha=json.load(fs)

print(alpha['offsety'])
