import socket, sys
from tests.test_platform import service, _Api
svc = service(automations={}); api = _Api(svc); port = api.server.server_port
def post(cl, size):
    s = socket.create_connection(("127.0.0.1", port))
    s.sendall(f"POST /api/auth/token HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\nContent-Length: {cl}\r\nConnection: close\r\n\r\n".encode())
    s.sendall(b"{" + b" " * (size - 2) + b"}"); s.shutdown(socket.SHUT_WR)
    data = s.recv(400).decode(errors="replace").splitlines()[0]; s.close(); return data
print("Content-Length 2000000, 2 MB body ->", post(2000000, 2_000_000))
print("Content-Length -1, 5 MB body      ->", post(-1, 5_000_000))
