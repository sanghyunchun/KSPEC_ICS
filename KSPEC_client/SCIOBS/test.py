import numpy as np
import json

dir='../../inputdata/motion/'
alpha=np.loadtxt(dir+'1_Pathdata_Alpha_motor.csv',delimiter=',')
beta=np.loadtxt(dir+'1_Pathdata_Beta_motor.csv',delimiter=',')
Fibnum=np.loadtxt('/media/shyunc/DATA/KSpec/KSPECICS_P5/Lib/Fibnum.def',dtype=str)


motion_alpha={}

#print(Fibnum)


for i  in range(150):
    motion_alpha[Fibnum[i]]=alpha[:,i]


print(motion_alpha)
