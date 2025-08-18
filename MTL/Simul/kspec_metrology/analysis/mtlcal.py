import numpy as np
from .findpeak import findpeak
from .matchfiber import matchfiber
from .fitdistortion import fitdistortion

def mtlcal(data_dir='./MTL/data/'):
    # Load Fiber positions and Fiducial flag------------------------------------------------
    x, y, fid_flag = np.load(data_dir+"pos.npy")
    fid_flag = fid_flag.astype(bool)
    npeaks = x.size

    _, xobs, yobs = findpeak(npeaks)

    imatch, theta_guess = matchfiber(x, y, xobs, yobs)

    _, _, dx, dy, _ = fitdistortion(x, y, fid_flag, xobs, yobs, imatch, theta_guess)

    return 'success', dx, dy 
