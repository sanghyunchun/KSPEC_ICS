def set_header_info(obstype: str='None', obsdate: str='19820913', TileID: str='0000', obsra: str='00:00:00.000',obsdec: str='00:00:00.000',
        exptime: int=10, expnum: str='None', projID: str='None', fwhm: float='9.99'):

        headerinfo = {'OBSDATE': obsdate, 'OBSTYPE': obstype, 'PROJID': projID, 'TileID': TileID, 'RA': obsra, 'DEC': obsdec, 'EXPTIME': exptime, 
            'EXPNUM': expnum, 'FWHM': fwhm}

        return headerinfo