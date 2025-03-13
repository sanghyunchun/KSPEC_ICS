import numpy as np



with open('ASPECS_obs_250218.txt',"r") as f:
    header = f.readline().strip().split()


data=np.loadtxt('ASPECS_obs_250218.txt',skiprows=1,dtype=str)

print("\t".join(header))
for row in data:
    print("\t".join(row))


tile_ids = set(row[0] for row in data)


select_tile='1472'


for row in data:
    if row[0] == select_tile:
        print(row[2])



