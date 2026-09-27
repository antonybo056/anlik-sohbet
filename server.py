"""
Anlık Sohbet: gerçek zamanlı sohbet sunucusu.

Aynı ağdaki (aynı Wi-Fi) cihazlar tarayıcıdan bağlanıp mesaj, emoji ve
fotoğraf gönderebilir, tepki verebilir, mesajlara yanıt verebilir.

Çalıştırma:
    pip install -r requirements.txt
    python server.py            (varsayılan port 8765)
    python server.py 9000       (başka bir port)

Sunucu açılınca ekranda yazan adresi diğer cihazın tarayıcısında aç.
"""

import asyncio
import base64
import json
import mimetypes
import os
import re
import secrets
import socket
import sys
import time
from http import HTTPStatus
from pathlib import Path

from websockets.asyncio.server import broadcast, serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Response

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
DATA = BASE / "data"
UPLOADS = DATA / "uploads"
HISTORY_FILE = DATA / "history.json"

HOST = "0.0.0.0"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", 8765))
MAX_HISTORY = 300                 # oda başına saklanan mesaj
MAX_TEXT = 4000                   # mesaj başına karakter
MAX_IMAGE = 6 * 1024 * 1024       # fotoğraf başına bayt
COLORS = ["#0f766e", "#b45309", "#7c3aed", "#be123c", "#1d4ed8", "#4d7c0f", "#a21caf", "#0e7490"]
IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}
UPLOAD_RE = re.compile(r"^[a-f0-9]{32}\.(png|jpg|gif|webp)$")
ROOM_RE = re.compile(r"[^a-z0-9çğıöşü_-]+")

rooms = {}      # oda adı -> {"clients": set(ws), "history": [mesaj, ...]}
sessions = {}   # ws -> {"id", "name", "color", "room"}
_save_task = None


# ---------------------------------------------------------------- yardımcılar
def now_ms():
    return int(time.time() * 1000)


def lan_urls():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))       # paket gönderilmez, sadece çıkış arayüzü bulunur
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            ips.add(ip)
    except OSError:
        pass
    ips = sorted(ip for ip in ips if not ip.startswith(("127.", "169.254.")))
    return [f"http://{ip}:{PORT}" for ip in ips]


def clean_room(value):
    room = ROOM_RE.sub("-", str(value or "").strip().lower().replace("İ", "i").replace("I", "ı"))
    return room.strip("-")[:32] or "genel"


def room_of(name):
    if name not in rooms:
        rooms[name] = {"clients": set(), "history": []}
    return rooms[name]


def users_in(room):
    seen = {}
    for ws in rooms[room]["clients"]:
        s = sessions.get(ws)
        if s and s["id"] not in seen:
            seen[s["id"]] = {"id": s["id"], "name": s["name"], "color": s["color"]}
    return sorted(seen.values(), key=lambda u: u["name"].lower())


def connections_of(room, uid):
    return sum(1 for ws in rooms[room]["clients"] if sessions.get(ws, {}).get("id") == uid)


def send_room(room, payload, exclude=None):
    targets = [ws for ws in rooms[room]["clients"] if ws is not exclude]
    broadcast(targets, json.dumps(payload, ensure_ascii=False))


def find_msg(room, mid):
    for m in reversed(rooms[room]["history"]):
        if m["id"] == mid:
            return m
    return None


def preview_of(m):
    if m["kind"] == "image":
        return "📷 Fotoğraf" + (f": {m['text'][:80]}" if m.get("text") else "")
    if m["kind"] == "deleted":
        return "Silinmiş mesaj"
    return m["text"][:120]


def add_message(room, msg):
    hist = rooms[room]["history"]
    hist.append(msg)
    del hist[:-MAX_HISTORY]
    schedule_save()
    send_room(room, {"type": "msg", "msg": msg})


def system(room, text):
    add_message(room, {"id": secrets.token_hex(8), "kind": "system", "text": text, "ts": now_ms()})


# ---------------------------------------------------------------- kalıcılık
def load_history():
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        for name, hist in data.items():
            room_of(name)["history"] = hist[-MAX_HISTORY:]
    except (OSError, ValueError):
        pass


def schedule_save():
    global _save_task
    if _save_task is None or _save_task.done():
        _save_task = asyncio.get_running_loop().create_task(_save_later())


async def _save_later():
    await asyncio.sleep(1.0)
    DATA.mkdir(exist_ok=True)
    data = {name: r["history"] for name, r in rooms.items() if r["history"]}
    tmp = HISTORY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, HISTORY_FILE)


# ---------------------------------------------------------------- HTTP
def http(status, body, ctype, cache="no-cache"):
    headers = Headers([("Content-Type", ctype), ("Content-Length", str(len(body))), ("Cache-Control", cache),
                       ("X-Content-Type-Options", "nosniff")])
    return Response(status.value, status.phrase, headers, body)


def process_request(connection, request):
    path = request.path.split("?", 1)[0]
    if path == "/ws":
        return None  # WebSocket el sıkışmasına devam
    if path in ("/", "/index.html"):
        return http(HTTPStatus.OK, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
    if path == "/info":
        return http(HTTPStatus.OK, json.dumps({"urls": lan_urls(), "port": PORT}).encode(), "application/json")
    if path.startswith("/uploads/"):
        name = path[len("/uploads/"):]
        f = UPLOADS / name
        if UPLOAD_RE.match(name) and f.is_file():
            ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
            return http(HTTPStatus.OK, f.read_bytes(), ctype, "public, max-age=31536000, immutable")
    if path == "/favicon.ico":
        return http(HTTPStatus.NO_CONTENT, b"", "image/x-icon")
    return http(HTTPStatus.NOT_FOUND, "Bulunamadı".encode(), "text/plain; charset=utf-8")


# ---------------------------------------------------------------- WebSocket
async def handler(ws):
    try:
        async for raw in ws:
            if not isinstance(raw, str):
                continue
            try:
                data = json.loads(raw)
            except ValueError:
                continue
            kind = data.get("type")
            if kind == "join":
                await on_join(ws, data)
            elif ws in sessions:
                s = sessions[ws]
                if kind == "msg":
                    on_text(s, data)
                elif kind == "image":
                    await on_image(ws, s, data)
                elif kind == "typing":
                    send_room(s["room"], {"type": "typing", "user": {"id": s["id"], "name": s["name"]},
                                          "on": bool(data.get("on"))}, exclude=ws)
                elif kind == "react":
                    on_react(s, data)
                elif kind == "delete":
                    on_delete(s, data)
    except ConnectionClosed:
        pass
    finally:
        leave(ws)


async def error(ws, text):
    try:
        await ws.send(json.dumps({"type": "error", "text": text}, ensure_ascii=False))
    except ConnectionClosed:
        pass


async def on_join(ws, data):
    name = " ".join(str(data.get("name", "")).split())[:32]
    if not name:
        await error(ws, "Bir ad yazmalısın.")
        return
    leave(ws)
    uid = str(data.get("uid", ""))
    if not re.fullmatch(r"[a-f0-9]{16,48}", uid):
        uid = secrets.token_hex(12)
    color = data.get("color") if data.get("color") in COLORS else COLORS[hash(uid) % len(COLORS)]
    room = clean_room(data.get("room"))
    r = room_of(room)
    first = connections_of(room, uid) == 0
    sessions[ws] = {"id": uid, "name": name, "color": color, "room": room}
    r["clients"].add(ws)
    await ws.send(json.dumps({"type": "welcome", "you": {"id": uid, "name": name, "color": color}, "room": room,
                              "history": r["history"], "users": users_in(room)}, ensure_ascii=False))
    if first:
        system(room, f"{name} sohbete katıldı")
    send_room(room, {"type": "users", "users": users_in(room)})
    print(f"  + {name} → #{room}  ({len(r['clients'])} bağlantı)")


def leave(ws):
    s = sessions.pop(ws, None)
    if not s:
        return
    room = s["room"]
    rooms[room]["clients"].discard(ws)
    if connections_of(room, s["id"]) == 0:
        send_room(room, {"type": "typing", "user": {"id": s["id"], "name": s["name"]}, "on": False})
        system(room, f"{s['name']} sohbetten ayrıldı")
    send_room(room, {"type": "users", "users": users_in(room)})
    print(f"  - {s['name']} ← #{room}")


def base_msg(s, kind, text, data):
    msg = {"id": secrets.token_hex(8), "kind": kind, "text": text, "ts": now_ms(),
           "user": {"id": s["id"], "name": s["name"], "color": s["color"]}, "reactions": {}}
    ref = find_msg(s["room"], str(data.get("reply_to", ""))) if data.get("reply_to") else None
    if ref and ref["kind"] != "system":
        msg["reply"] = {"id": ref["id"], "name": ref["user"]["name"], "text": preview_of(ref)}
    return msg


def on_text(s, data):
    text = str(data.get("text", "")).strip()[:MAX_TEXT]
    if text:
        add_message(s["room"], base_msg(s, "text", text, data))


async def on_image(ws, s, data):
    m = re.match(r"^data:(image/[a-z+]+);base64,(.+)$", str(data.get("data", "")), re.S)
    if not m or m.group(1) not in IMAGE_TYPES:
        await error(ws, "Bu dosya türü desteklenmiyor. PNG, JPG, GIF veya WEBP gönder.")
        return
    try:
        blob = base64.b64decode(m.group(2), validate=True)
    except ValueError:
        await error(ws, "Fotoğraf okunamadı.")
        return
    if len(blob) > MAX_IMAGE:
        await error(ws, "Fotoğraf 6 MB'tan büyük olamaz.")
        return
    UPLOADS.mkdir(parents=True, exist_ok=True)
    name = f"{secrets.token_hex(16)}.{IMAGE_TYPES[m.group(1)]}"
    (UPLOADS / name).write_bytes(blob)
    msg = base_msg(s, "image", str(data.get("text", "")).strip()[:MAX_TEXT], data)
    msg["url"] = f"/uploads/{name}"
    msg["w"], msg["h"] = int(data.get("w") or 0), int(data.get("h") or 0)
    add_message(s["room"], msg)


def on_react(s, data):
    emoji = str(data.get("emoji", ""))
    msg = find_msg(s["room"], str(data.get("id", "")))
    if not msg or msg["kind"] in ("system", "deleted") or not emoji or len(emoji) > 16:
        return
    reactions = msg.setdefault("reactions", {})
    ids = reactions.setdefault(emoji, [])
    if s["id"] in ids:
        ids.remove(s["id"])
    else:
        ids.append(s["id"])
    if not ids:
        del reactions[emoji]
    schedule_save()
    send_room(s["room"], {"type": "update", "msg": msg})


def on_delete(s, data):
    msg = find_msg(s["room"], str(data.get("id", "")))
    if not msg or msg.get("user", {}).get("id") != s["id"] or msg["kind"] == "deleted":
        return
    if msg["kind"] == "image" and msg.get("url"):
        try:
            (UPLOADS / msg["url"].rsplit("/", 1)[1]).unlink()
        except OSError:
            pass
    msg.update({"kind": "deleted", "text": "", "reactions": {}})
    msg.pop("url", None)
    schedule_save()
    send_room(s["room"], {"type": "update", "msg": msg})


# ---------------------------------------------------------------- başlat
async def main():
    load_history()
    async with serve(handler, HOST, PORT, process_request=process_request, max_size=10 * 1024 * 1024):
        urls = lan_urls()
        print("\n  Anlık Sohbet sunucusu çalışıyor.\n")
        print(f"  Bu bilgisayarda:   http://localhost:{PORT}")
        for u in urls:
            print(f"  Diğer cihazlarda:  {u}")
        if not urls:
            print("  (Ağ adresi bulunamadı. Bilgisayar bir Wi-Fi ya da kablolu ağa bağlı mı?)")
        print("\n  Cihazlar aynı Wi-Fi ağında olmalı. Kapatmak için Ctrl+C.\n")
        await asyncio.get_running_loop().create_future()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="replace")   # eski Windows konsollarında Türkçe karakterler için
    except AttributeError:
        pass
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n  Sunucu kapatıldı.")
