import socket

sersocket=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
sersocket.bind(('127.0.0.1',8888))
sersocket.listen()

while True:
    print('>>Wait')
    
    client_socket,addr=sersocket.accept()
#    print(f'IP: {addr}')
#    print(f'client socket info: {client_socket}')
    msg=client_socket.recv(1024)
#    print(msg.decode())
    message='Hi'
    client_socket.send(message.encode())
