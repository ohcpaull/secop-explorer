#!/usr/bin/env python3
"""
secop_bridge.py  --  WebSocket <-> TCP bridge for SECoP nodes.

Web browsers cannot open raw TCP sockets, and a standard SECoP node speaks a
line-based text protocol over plain TCP (default port 10767).  This tiny bridge
relays a browser WebSocket connection to that TCP port, one SECoP line per
WebSocket message, in both directions.

  * Pure Python standard library -- no pip install required.
  * One running bridge can serve any number of nodes: the browser passes the
    target host/port in the WebSocket URL query string.

Usage
-----
    python3 secop_bridge.py                 # listens on 127.0.0.1:1337
    python3 secop_bridge.py --listen 0.0.0.0:1337

The web page then connects to:
    ws://127.0.0.1:1337/?host=<secop-host>&port=<secop-port>

(The "SECoP Node Explorer" page builds that URL for you from the host/port
fields when it is in "Via bridge" mode.)
"""
import argparse
import asyncio
import base64
import hashlib
import struct
import sys
import urllib.parse

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


async def read_http_headers(reader):
    lines = []
    while True:
        line = await reader.readline()
        if not line or line in (b"\r\n", b"\n"):
            break
        lines.append(line.decode("latin1").rstrip("\r\n"))
        if len(lines) > 200:
            break
    if not lines:
        return None, {}
    headers = {}
    for h in lines[1:]:
        if ":" in h:
            k, v = h.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    return lines[0], headers


def ws_frame(payload: bytes, opcode: int = 0x1) -> bytes:
    out = bytearray([0x80 | opcode])
    n = len(payload)
    if n < 126:
        out.append(n)
    elif n < 65536:
        out.append(126)
        out += struct.pack(">H", n)
    else:
        out.append(127)
        out += struct.pack(">Q", n)
    out += payload
    return bytes(out)


async def ws_read_frame(reader):
    """Return (opcode, payload_bytes). Reassembles fragmented frames."""
    payload = bytearray()
    opcode0 = None
    while True:
        b0, b1 = await reader.readexactly(2)
        fin = b0 & 0x80
        opcode = b0 & 0x0F
        masked = b1 & 0x80
        length = b1 & 0x7F
        if length == 126:
            length = struct.unpack(">H", await reader.readexactly(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", await reader.readexactly(8))[0]
        mask = await reader.readexactly(4) if masked else b"\x00\x00\x00\x00"
        chunk = bytearray(await reader.readexactly(length))
        for i in range(len(chunk)):
            chunk[i] ^= mask[i % 4]
        if opcode == 0x0:  # continuation
            payload += chunk
        else:
            opcode0 = opcode
            payload += chunk
        if fin:
            return opcode0, bytes(payload)


async def pipe_tcp_to_ws(tcp_reader, ws_writer):
    while True:
        line = await tcp_reader.readline()
        if not line:
            raise ConnectionError("SECoP node closed the connection")
        ws_writer.write(ws_frame(line.rstrip(b"\r\n")))
        await ws_writer.drain()


async def pipe_ws_to_tcp(ws_reader, ws_writer, tcp_writer):
    while True:
        opcode, data = await ws_read_frame(ws_reader)
        if opcode == 0x8:  # close
            raise ConnectionError("browser closed the WebSocket")
        if opcode == 0x9:  # ping -> pong
            ws_writer.write(ws_frame(data, 0xA))
            await ws_writer.drain()
            continue
        if opcode not in (0x1, 0x2):
            continue
        if not data.endswith(b"\n"):
            data += b"\n"
        tcp_writer.write(data)
        await tcp_writer.drain()


async def handle_client(reader, writer):
    peer = writer.get_extra_info("peername")
    tcp_writer = None
    try:
        request_line, headers = await read_http_headers(reader)
        if not request_line:
            writer.close()
            return
        try:
            _method, path, _ver = request_line.split(" ", 2)
        except ValueError:
            writer.close()
            return

        key = headers.get("sec-websocket-key")
        if headers.get("upgrade", "").lower() != "websocket" or not key:
            body = (b"secop_bridge: this endpoint speaks WebSocket only.\n"
                    b"Connect with  ws://<this-host>/?host=<secop-host>&port=<secop-port>\n")
            writer.write(
                b"HTTP/1.1 426 Upgrade Required\r\n"
                b"Content-Type: text/plain\r\n"
                b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                b"Connection: close\r\n\r\n" + body
            )
            await writer.drain()
            writer.close()
            return

        accept = base64.b64encode(
            hashlib.sha1((key + WS_GUID).encode()).digest()
        ).decode()
        writer.write(
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Upgrade: websocket\r\n"
            b"Connection: Upgrade\r\n"
            b"Sec-WebSocket-Accept: " + accept.encode() + b"\r\n\r\n"
        )
        await writer.drain()

        q = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
        host = q.get("host", ["localhost"])[0]
        try:
            port = int(q.get("port", ["10767"])[0])
        except ValueError:
            port = 10767
        print(f"[bridge] {peer} -> connecting to SECoP node {host}:{port}", flush=True)

        try:
            tcp_reader, tcp_writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=10
            )
        except Exception as exc:  # noqa: BLE001
            msg = f"__bridge_error__ cannot reach {host}:{port}: {exc}"
            writer.write(ws_frame(msg.encode()))
            await writer.drain()
            writer.write(ws_frame(b"", 0x8))
            await writer.drain()
            writer.close()
            print(f"[bridge] {peer} -- {msg}", flush=True)
            return

        t1 = asyncio.ensure_future(pipe_tcp_to_ws(tcp_reader, writer))
        t2 = asyncio.ensure_future(pipe_ws_to_tcp(reader, writer, tcp_writer))
        done, pending = await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        for t in done:
            exc = t.exception()
            if exc and not isinstance(exc, (ConnectionError, asyncio.IncompleteReadError,
                                            ConnectionResetError, BrokenPipeError)):
                print(f"[bridge] {peer} error: {exc!r}", file=sys.stderr, flush=True)
    except (ConnectionError, asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
        pass
    except Exception as exc:  # noqa: BLE001
        print(f"[bridge] {peer} unexpected error: {exc!r}", file=sys.stderr, flush=True)
    finally:
        if tcp_writer is not None:
            try:
                tcp_writer.close()
            except Exception:
                pass
        try:
            writer.write(ws_frame(b"", 0x8))
            await writer.drain()
        except Exception:
            pass
        try:
            writer.close()
        except Exception:
            pass
        print(f"[bridge] {peer} disconnected", flush=True)


async def main_async(host, port):
    server = await asyncio.start_server(handle_client, host, port)
    addrs = ", ".join(str(s.getsockname()) for s in server.sockets)
    print(f"[bridge] listening on {addrs}")
    print(f"[bridge] browser URL:  ws://{host}:{port}/?host=<secop-host>&port=<secop-port>")
    async with server:
        await server.serve_forever()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--listen", default="127.0.0.1:1337",
                    help="host:port to listen on (default: 127.0.0.1:1337)")
    args = ap.parse_args()
    host, _, port = args.listen.rpartition(":")
    host = host or "127.0.0.1"
    try:
        port = int(port)
    except ValueError:
        ap.error("--listen must be host:port")
    try:
        asyncio.run(main_async(host, port))
    except KeyboardInterrupt:
        print("\n[bridge] stopped")


if __name__ == "__main__":
    main()
