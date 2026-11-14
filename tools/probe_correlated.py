import asyncio
import json
import os
import socket
import time
import aiohttp


def crc8(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x31) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


def make_frame(
    action: int,
    domain: int,
    attr: int,
    payload: bytes = b"",
    seq: int = 1,
    rev: int = 1,
) -> bytes:
    body = bytes([action, domain, attr]) + payload
    header = bytes([rev, seq, (len(body) >> 8) & 0xFF, len(body) & 0xFF])
    frame_no_crc = header + body
    return frame_no_crc + bytes([crc8(frame_no_crc)])


def parse_frames(buf: bytes):
    idx = 0
    out = []
    while idx + 4 <= len(buf):
        cnt = (buf[idx + 2] << 8) | buf[idx + 3]
        end = idx + cnt + 5
        if end > len(buf):
            break
        frame = buf[idx:end]
        idx = end
        body = frame[4:-1]
        out.append(
            {
                "rev": frame[0],
                "seq": frame[1],
                "body": list(body),
                "crc_ok": crc8(frame[:-1]) == frame[-1],
            }
        )
    return out, buf[idx:]


env = dict(
    line.strip().split("=", 1)
    for line in open(os.path.expanduser("~/.hermes/.env"))
    if "=" in line and not line.startswith("#")
)
ha_url = env["HA_URL"].replace("http://", "ws://") + "/api/websocket"
ha_token = env["HA_TOKEN"].strip("\"'")
entry_id = "<APRILAIRE_CONFIG_ENTRY_ID>"


async def set_ha_disabled(disabled_by):
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(ha_url, max_msg_size=0) as ws:
            await ws.receive_json()
            await ws.send_json({"type": "auth", "access_token": ha_token})
            await ws.receive_json()
            await ws.send_json(
                {
                    "id": 1,
                    "type": "config_entries/disable",
                    "entry_id": entry_id,
                    "disabled_by": disabled_by,
                }
            )
            res = await ws.receive_json()
            print("HA disable", disabled_by, "->", res.get("result"))


print("Disabling HA entry...")
asyncio.run(set_ha_disabled("user"))
time.sleep(2.0)

try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.6)
    s.connect(("192.0.2.45", 7000))
    buf = b""
    seq = 1

    def query(dom, attr, payload=b"", rev=1):
        global seq, buf
        my_seq = seq
        seq = (seq % 120) + 1
        s.sendall(make_frame(2, dom, attr, payload, seq=my_seq, rev=rev))
        deadline = time.time() + 0.8
        while time.time() < deadline:
            try:
                chunk = s.recv(1024)
                if not chunk:
                    break
                buf += chunk
                frames, buf = parse_frames(buf)
                for f in frames:
                    if f["seq"] == my_seq:
                        return f
            except socket.timeout:
                break
        return None

    print("=== Comparing rev=1, rev=2, rev=3, rev=0 ===")
    for dom, attr in [(2, 1), (5, 1), (5, 2), (7, 6), (8, 4), (8, 5), (8, 6), (3, 4)]:
        for rev in [1, 2, 3, 0]:
            res = query(dom, attr, b"", rev=rev)
            print(f"dom={dom} attr={attr} rev={rev} -> {res}")

    print("=== Checking Domain 1..12 attrs 6..20 with exact correlation ===")
    for dom in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 13]:
        for attr in range(1, 20):
            res = query(dom, attr, b"", rev=1)
            if res and not (len(res["body"]) == 2 and res["body"][0] == 6 and res["body"][1] in (6, 7)):
                print(f"  ({dom:2d}, {attr:2d}) rev=1 -> {res['body']}")
            res2 = query(dom, attr, b"", rev=2)
            if res2 and not (len(res2["body"]) == 2 and res2["body"][0] == 6 and res2["body"][1] in (4, 6, 7)):
                if not res or res2["body"] != res["body"]:
                    print(f"  ({dom:2d}, {attr:2d}) rev=2 DIFF -> {res2['body']}")
    s.close()
finally:
    print("Re-enabling HA entry...")
    asyncio.run(set_ha_disabled(None))
