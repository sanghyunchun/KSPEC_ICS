import numpy as np
from scipy.optimize import curve_fit
from kspec_metrology.analysis.utils import transform_polynomial, transform, camera2focal_coeff
from kspec_metrology.logging.log import get_logger

def fitdistortion(x, y, fid_flag
                  , xobs, yobs
                  , imatch, theta_guess, xoff_guess, yoff_guess):
                    
    xobs_match = xobs[imatch]
    yobs_match = yobs[imatch]

    xfit = np.concatenate((xobs_match[fid_flag], xobs_match[fid_flag]))
    yfit = np.concatenate((yobs_match[fid_flag], yobs_match[fid_flag]))
    ccd_fit = np.concatenate((x[fid_flag], y[fid_flag]))
    
    coeff_temp = np.copy(camera2focal_coeff)
    coeff_temp[1] = theta_guess
    coeff_temp[2] = xoff_guess
    coeff_temp[3] = yoff_guess
    inv_popt_obs, _ = curve_fit(transform_polynomial, (xfit, yfit), ccd_fit
                       , maxfev=20000
                       , p0=coeff_temp
                       )

    xfocal_obs, yfocal_obs = transform(xobs_match, yobs_match, inv_popt_obs)

    dx = xfocal_obs-x
    dy = yfocal_obs-y

    # 각도 변환은 arm 길이가 필요하므로 mtlcal에서 한다.
    return xfocal_obs, yfocal_obs, dx, dy, inv_popt_obs
