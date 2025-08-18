import redis



r=redis.Redis(host='localhost',port=6379,decode_responses=True)
value=r.get('dome_error')

print(value)


if value == '0001':
    print('Telescope slew finished')


