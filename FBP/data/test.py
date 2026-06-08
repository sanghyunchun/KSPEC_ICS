import json

with open('motion_alpha.info','r') as f:
    data=json.load(f)


print(data.keys())
