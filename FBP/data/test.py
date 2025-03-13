import json

with open('motion.info','r') as f:
    data=json.load(f)

print(data['tileid'])
