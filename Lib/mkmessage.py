import json

def common():
    dict_data={'inst': 'None', 'func' : 'None', 'savedata': 'False', 'filename': 'None', 'process': 'ING', 'message': 'None',
            'script': 'False','status': 'fail'}
    return dict_data

def gfamsg():
    dict_data=common()
    dict_data.update(inst='GFA')
    return dict_data

def endomsg():
    dict_data=common()
    dict_data.update(inst='ENDO')
    return dict_data

def adcmsg():
    dict_data=common()
    update_data={'zdist': 'None','RA': 'None', 'DEC': 'None'}
    dict_data.update(update_data)
    dict_data.update(inst='ADC')
    return dict_data

def fbpmsg():
    dict_data=common()
#    update_data={'zdist': 'None'}
#    dict_data.update(update_data)
    dict_data.update(inst='FBP')
    return dict_data

def lampmsg():
    dict_data=common()
#    update_data={'zdist': 'None'}
#    dict_data.update(update_data)
    dict_data.update(inst='LAMP')
    return dict_data

def mtlmsg():
    dict_data=common()
    update_data={'time': 'None'}
#    dict_data.update(update_data)
    dict_data.update(inst='MTL')
    return dict_data

def specmsg():
    dict_data=common()
    update_data={'time': 'None','numframe': 'None'}
    dict_data.update(update_data)
    dict_data.update(inst='SPEC')
    return dict_data

