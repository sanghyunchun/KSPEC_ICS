import numpy as np
from photutils.detection import find_peaks
from astropy.io import fits
from kspec_metrology.analysis.utils import com
from kspec_metrology.logging.log import get_logger

def findpeak(npeaks
            , data_dir='./data/'
            , nexposure=1
            , threshold=5e3
            , boxsize=40
            , nwindow=40
            , SaveFiberImage=False
            , mode="Raw"
            , x=None, y=None):
    log = get_logger()

    xchip = np.linspace(-5879.5, 5879.5, 11760)*3.76e-3
    ychip = np.linspace(-4420.5, 4420.5, 8842)*3.76e-3
    
    #---Stack "nframe" Image----------------------------------------------------------------------------------------------------------
    im = np.zeros((8842, 11760))
    for iframe in range(nexposure):
        im += fits.getdata(data_dir + f'test{iframe}.fits').astype(np.float64) / nexposure


    #---Find Peaks Using any method---------------------------------------------------------------------------------------------------    
    log.info("Start finding peaks with %s", mode)
    if mode == "Raw":
        peak_table = find_peaks(im, threshold=threshold, box_size=boxsize, npeaks=npeaks)
        xf, yf = peak_table['x_peak'].data, peak_table['y_peak'].data   
        log.info(f"Found {xf.size} peaks")
        if xf.size > npeaks:
            log.warning("Too many peaks detected")
        elif xf.size < npeaks:
            log.warning(f"{npeaks-xf.size} peaks are not detected")
    elif mode=="Predict":
        from kspec_metrology.analysis.utils import transform, focal2camera_coeff
        coeff_temp = np.copy(focal2camera_coeff)
        coeff_temp[1] = 5.21
        xpredict, ypredict = transform(x, y, coeff_temp)

    #---Calculate Center--------------------------------------------------------------------------------------------------------------
    xobs = np.zeros(npeaks)
    yobs = np.copy(xobs)

    if SaveFiberImage:
        im_crop_full = np.zeros( (npeaks, nwindow*2, nwindow*2))

    for ifiber in range(npeaks):
        if mode != "Predict":
            ipredict = np.argmin( np.abs(xchip[xf[ifiber]]-xchip) )
            jpredict = np.argmin( np.abs(ychip[yf[ifiber]]-ychip) )
        else:
            ipredict = np.argmin( np.abs(xpredict[ifiber]-xchip) )
            jpredict = np.argmin( np.abs(ypredict[ifiber]-ychip) )

        im_crop = im[jpredict-nwindow:jpredict+nwindow, ipredict-nwindow:ipredict+nwindow]

        x_crop = xchip[ipredict-nwindow:ipredict+nwindow]
        y_crop = ychip[jpredict-nwindow:jpredict+nwindow]

        xobs[ifiber], yobs[ifiber] = com(im_crop, x_crop, y_crop)

        if SaveFiberImage:
            im_crop_full[ifiber] = im_crop

    if SaveFiberImage:
        np.save(data_dir+f'fiberimage.npy', im_crop_full)

    return im, xobs, yobs
