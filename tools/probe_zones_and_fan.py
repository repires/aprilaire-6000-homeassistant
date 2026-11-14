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
    return out


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

results = {"scan": [], "zone_tests": []}
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.25)
    s.connect(("192.0.2.45", 7000))
    seq = 1

    # 1. Test reading (2,1), (5,1), (5,2), (7,6), (8,4), (3,3), (3,4) with payload=[1] or [2] or rev=2
    for dom, attr in [(2, 1), (5, 1), (5, 2), (7, 6), (8, 4), (3, 3), (3, 4)]:
        for extra_label, payload, rev in [
            ("payload=1", b"\x01", 1),
            ("payload=2", b"\x02", 1),
            ("rev=2", b"", 2),
        ]:
            s.sendall(make_frame(2, dom, attr, payload, seq=seq, rev=rev))
            try:
                rx = s.recv(1024)
                frames = parse_frames(rx)
            except socket.timeout:
                frames = []
            results["zone_tests"].append(
                {"dom": dom, "attr": attr, "test": extra_label, "frames": frames}
            )
            seq = (seq % 120) + 1

    # 2. Scan attributes 1..22 across domains 1..15 that we haven't checked yet
    already = {
        (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 6),
        (1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6),
        (2, 1), (2, 2), (2, 3), (2, 4), (2, 5), (2, 6), (2, 7), (2, 8),
        (3, 1), (3, 2), (3, 3), (3, 4), (3, 5),
        (4, 1), (4, 2), (4, 3),
        (5, 1), (5, 2), (5, 3), (5, 4), (5, 5),
        (6, 1), (6, 2),
        (7, 1), (7, 2), (7, 3), (7, 4), (7, 5), (7, 6), (7, 7), (7, 8), (7, 9),
        (10, 1), (10, 2),
    }
    for dom in range(1, 16):
        for attr in range(1, 22):
            if (dom, attr) in already:
                continue
            s.sendall(make_frame(2, dom, attr, b"", seq=seq, rev=1))
            try:
                rx = s.recv(1024)
                frames = parse_frames(rx)
            except socket.timeout:
                frames = []
            interesting = False
            for f in frames:
                b = f["body"]
                if not (len(b) == 2 and b[0] == 6 and b[1] in (6, 7)):
                    interesting = True
            if interesting:
                results["scan"].append({"dom": dom, "attr": attr, "frames": frames})
                print(f"INTERESTING ({dom}, {attr}): {frames}")
            if frames and len(frames[0]["body"]) == 2 and frames[0]["body"] == [6, 6]:
                break
            seq = (seq % 120) + 1
    s.close()
finally:
    print("Re-enabling HA entry...")
    asyncio.run(set_ha_disabled(None))

with open("/tmp/aprilaire_probe2.json", "w") as f:
    json.dump(results, f, indent=2)
print("Done. Zone tests:")
for zt in results["zone_tests"]:
    print(zt)
