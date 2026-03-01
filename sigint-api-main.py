"""TETRA Scanner API Server - bridges tetra-kit decoder to web clients."""

import asyncio
import json
import time
import os
import logging
import xmlrpc.client
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from database import init_db, get_db, DB_PATH
from ingestor import start_udp_listener, ws_clients, set_db_callback, audio_ws_clients, start_audio_listener, fft_ws_clients, start_fft_listener

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tetra.api")

RADIO_RPC = "http://127.0.0.1:42001"
RECORDINGS_DIR = "/opt/tetra-scanner/recordings"
WEB_DIR = "/opt/tetra-scanner/web"


async def persist_frame(frame: dict):
    """Store a decoded TETRA frame in the database."""
    db = await get_db()
    try:
        ts = frame.get("_ts", time.time())
        raw = json.dumps(frame)

        # Determine event type from tetra-kit JSON structure
        event_type = "unknown"
        if "SYSTEM INFO" in raw or "sysinfo" in raw.lower():
            event_type = "sysinfo"
        elif "D-SETUP" in raw or "d_setup" in raw.lower():
            event_type = "d_setup"
        elif "D-RELEASE" in raw or "d_release" in raw.lower():
            event_type = "d_release"
        elif "D-CONNECT" in raw or "d_connect" in raw.lower():
            event_type = "d_connect"
        elif "SDS" in raw or "sds" in raw.lower():
            event_type = "sds"
        elif "speech" in raw.lower() or "voice" in raw.lower():
            event_type = "voice"
        elif "MAC" in raw:
            event_type = "mac"

        freq = frame.get("frequency", frame.get("freq", None))
        ts_slot = frame.get("timeslot", frame.get("tn", None))

        await db.execute(
            "INSERT INTO events (ts, event_type, frequency, timeslot, json_raw) VALUES (?,?,?,?,?)",
            (ts, event_type, freq, ts_slot, raw),
        )

        # If it's a call setup, also insert into calls table
        if event_type == "d_setup":
            caller = frame.get("calling_party", frame.get("caller_ssi", None))
            called = frame.get("called_party", frame.get("called_ssi", None))
            call_id = frame.get("call_identifier", frame.get("call_id", None))
            encrypted = 1 if frame.get("encryption", 0) else 0
            await db.execute(
                "INSERT INTO calls (ts_start, caller_ssi, called_ssi, call_id, frequency, timeslot, encrypted) VALUES (?,?,?,?,?,?,?)",
                (ts, caller, called, call_id, freq, ts_slot, encrypted),
            )

        # If it's an SDS message
        if event_type == "sds":
            from_ssi = frame.get("from_ssi", frame.get("calling_party", None))
            to_ssi = frame.get("to_ssi", frame.get("called_party", None))
            content = frame.get("text", frame.get("sds_data", ""))
            await db.execute(
                "INSERT INTO sds_messages (ts, from_ssi, to_ssi, message_type, content, json_raw) VALUES (?,?,?,?,?,?)",
                (ts, from_ssi, to_ssi, "sds", str(content), raw),
            )

        await db.commit()
    finally:
        await db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown."""
    await init_db()
    set_db_callback(persist_frame)
    udp_transport = await start_udp_listener(42100)
    audio_transport = await start_audio_listener(42002)
    fft_transport = await start_fft_listener(42003)
    logger.info("TETRA Scanner API started")
    yield
    udp_transport.close()
    fft_transport.close()
    logger.info("TETRA Scanner API stopped")


app = FastAPI(title="TETRA Scanner", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- WebSocket endpoint for real-time stream ---
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    logger.info(f"WebSocket client connected ({len(ws_clients)} total)")
    try:
        while True:
            # Keep connection alive, client can send commands
            data = await ws.receive_text()
            # Future: handle client commands (tune frequency, etc.)
    except WebSocketDisconnect:
        ws_clients.discard(ws)
        logger.info(f"WebSocket client disconnected ({len(ws_clients)} total)")


@app.websocket("/ws/audio")
async def audio_websocket_endpoint(ws: WebSocket):
    await ws.accept()
    audio_ws_clients.add(ws)
    logger.info(f"Audio WebSocket client connected ({len(audio_ws_clients)} total)")
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        audio_ws_clients.discard(ws)
        logger.info(f"Audio WebSocket client disconnected ({len(audio_ws_clients)} total)")


@app.websocket("/ws/fft")
async def fft_websocket_endpoint(ws: WebSocket):
    await ws.accept()
    fft_ws_clients.add(ws)
    logger.info(f"FFT WebSocket client connected ({len(fft_ws_clients)} total)")
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        fft_ws_clients.discard(ws)
        logger.info(f"FFT WebSocket client disconnected ({len(fft_ws_clients)} total)")


# --- REST API endpoints ---
@app.get("/api/status")
async def get_status():
    """System status overview."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT COUNT(*) FROM events")
        total_events = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT COUNT(*) FROM calls")
        total_calls = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT COUNT(*) FROM sds_messages")
        total_sds = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT MAX(ts) FROM events")
        last_event = (await cursor.fetchone())[0]
        return {
            "total_events": total_events,
            "total_calls": total_calls,
            "total_sds": total_sds,
            "last_event_ts": last_event,
            "ws_clients": len(ws_clients),
            "uptime": time.time(),
        }
    finally:
        await db.close()


@app.get("/api/events")
async def get_events(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    event_type: str = Query(None),
    since: float = Query(None),
):
    """Query stored events."""
    db = await get_db()
    try:
        db.row_factory = aiosqlite_row_factory
        query = "SELECT * FROM events WHERE 1=1"
        params = []
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        if since:
            query += " AND ts >= ?"
            params.append(since)
        query += " ORDER BY ts DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


@app.get("/api/calls")
async def get_calls(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    since: float = Query(None),
):
    """Query call records."""
    db = await get_db()
    try:
        db.row_factory = aiosqlite_row_factory
        query = "SELECT * FROM calls WHERE 1=1"
        params = []
        if since:
            query += " AND ts_start >= ?"
            params.append(since)
        query += " ORDER BY ts_start DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


@app.get("/api/sds")
async def get_sds(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Query SDS messages."""
    db = await get_db()
    try:
        db.row_factory = aiosqlite_row_factory
        cursor = await db.execute(
            "SELECT * FROM sds_messages ORDER BY ts DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


@app.get("/api/recordings")
async def list_recordings():
    """List available voice recordings."""
    files = []
    if os.path.exists(RECORDINGS_DIR):
        for f in sorted(os.listdir(RECORDINGS_DIR), reverse=True):
            if f.endswith((".wav", ".ogg", ".raw", ".out")):
                path = os.path.join(RECORDINGS_DIR, f)
                files.append({"name": f, "size": os.path.getsize(path)})
    return files


@app.get("/api/recordings/{filename}")
async def get_recording(filename: str):
    """Download a specific recording."""
    path = os.path.join(RECORDINGS_DIR, filename)
    if os.path.exists(path):
        return FileResponse(path)
    return JSONResponse({"error": "not found"}, status_code=404)


def aiosqlite_row_factory(cursor, row):
    """Convert rows to dicts."""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}




@app.post("/api/tune")
def tune_radio(body: dict):
    """Retune SDR frequency and/or gain at runtime via XML-RPC."""
    try:
        rpc = xmlrpc.client.ServerProxy(RADIO_RPC)
        if "frequency" in body:
            rpc.set_freq(float(body["frequency"]))
        if "gain" in body:
            rpc.set_gain(float(body["gain"]))
        if "ppm" in body:
            rpc.set_ppm(float(body["ppm"]))
        return {"frequency": rpc.get_freq(), "gain": rpc.get_gain(), "ppm": rpc.get_ppm()}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=503)


@app.get("/api/radio")
def get_radio_status():
    """Get current SDR frequency, gain, PPM, and mode."""
    try:
        rpc = xmlrpc.client.ServerProxy(RADIO_RPC)
        return {
            "frequency": rpc.get_freq(),
            "gain": rpc.get_gain(),
            "ppm": rpc.get_ppm(),
            "mode": rpc.get_mode(),
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=503)


@app.post("/api/mode")
def set_radio_mode(body: dict):
    """Switch demodulation mode at runtime via XML-RPC."""
    try:
        rpc = xmlrpc.client.ServerProxy(RADIO_RPC)
        mode = body.get("mode", "tetra")
        result = rpc.set_mode(mode)
        return {"mode": result}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=503)


# Serve the web UI if it exists
if os.path.exists(os.path.join(WEB_DIR, "index.html")):
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
else:
    @app.get("/")
    async def root():
        return {"message": "TETRA Scanner API", "docs": "/docs"}
