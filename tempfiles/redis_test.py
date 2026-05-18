import redis
r=redis.Redis(host='192.168.15.121', port=6379,decode_responses=True)

value = r.get('dome_error')
print(value)
