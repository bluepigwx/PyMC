"""临时 Agent 服务端：等 PyMC 客户端连上来，下发建造指令。

用法：
    uv run python scene_server.py
然后启动 main.py（客户端会连 localhost:8001）。
"""
import socket
import struct
import json
import time

HOST = "0.0.0.0"
PORT = 8001
HEADER = ">I"


def send_frame(sock, obj):
    payload = json.dumps(obj).encode("utf-8")
    sock.sendall(struct.pack(HEADER, len(payload)) + payload)


def recv_exactly(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("client disconnected")
        buf.extend(chunk)
    return bytes(buf)


def recv_frame(sock):
    (length,) = struct.unpack(HEADER, recv_exactly(sock, 4))
    return json.loads(recv_exactly(sock, length).decode("utf-8"))


def pyramid_regions(cx=0, cz=0, base_y=1, half=6, block=12):
    """金字塔：每层向内收 1 格，共 half+1 层。"""
    regions = []
    for i in range(half + 1):
        r = half - i
        y = base_y + i
        regions.append({
            "type": block,
            "x": [cx - r, cx + r],
            "y": [y, y],
            "z": [cz - r, cz + r],
        })
    return regions


def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(1)
    print(f"listening on {HOST}:{PORT}, waiting for PyMC client...", flush=True)

    conn, addr = srv.accept()
    print(f"client connected: {addr}", flush=True)

    send_frame(conn, {"cmd": "connected", "params": {"session_id": "local-builder"}})

    regions = pyramid_regions()
    send_frame(conn, {
        "cmd": "set_blocks_region",
        "request_id": "pyramid-1",
        "params": {"regions": regions},
    })
    print(f"sent set_blocks_region with {len(regions)} layers", flush=True)

    conn.settimeout(60)
    try:
        resp = recv_frame(conn)
        print(f"response: {resp}", flush=True)
    except Exception as e:
        print(f"recv failed: {e}", flush=True)

    # 保持连接，方便后续继续下发指令
    conn.settimeout(None)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        conn.close()
        srv.close()


if __name__ == "__main__":
    main()
