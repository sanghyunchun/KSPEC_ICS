import numpy as np
from scipy.optimize import curve_fit
from .utils import transform_polynomial, transform, camera2focal_coeff

def fitdistortion(x, y, fid_flag
                  , xobs, yobs
                  , imatch, theta_guess):

    xobs_match = xobs[imatch]
    yobs_match = yobs[imatch]

    xfit = np.concatenate((xobs_match[fid_flag], xobs_match[fid_flag]))
    yfit = np.concatenate((yobs_match[fid_flag], yobs_match[fid_flag]))
    ccd_fit = np.concatenate((x[fid_flag], y[fid_flag]))
    
    coeff_temp = np.copy(camera2focal_coeff)
    coeff_temp[1] = theta_guess
    inv_popt_obs, _ = curve_fit(transform_polynomial, (xfit, yfit), ccd_fit
                       , maxfev=10000
                       , p0=coeff_temp
                       )

    xfocal_obs, yfocal_obs = transform(xobs_match, yobs_match, inv_popt_obs)

    dx = xfocal_obs-x
    dy = yfocal_obs-y

    return xfocal_obs, yfocal_obs, dx, dy, inv_popt_obs
