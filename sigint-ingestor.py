"""Ingest tetra-kit JSON output via UDP and push to DB + WebSocket clients."""

import asyncio
import json
import time
import logging

logger = logging.getLogger("tetra.ingestor")

# Subscribers for real-time WebSocket broadcast
ws_clients: set = set()
audio_ws_clients: set = set()
fft_ws_clients: set = set()
# Callback for DB persistence
_db_callback = None


def set_db_callback(cb):
    global _db_callback
    _db_callback = cb


class TetraUDPProtocol(asyncio.DatagramProtocol):
    """Receive JSON datagrams from tetra-kit decoder on UDP 42100."""

    def __init__(self):
        self.buffer = b""

    def datagram_received(self, data: bytes, addr):
        try:
            lines = data.decode("utf-8", errors="replace").strip().split("\n")
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    frame = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug(f"Non-JSON line: {line[:80]}")
                    continue

                asyncio.ensure_future(self._process_frame(frame))
        except Exception as e:
            logger.error(f"UDP receive error: {e}")

    async def _process_frame(self, frame: dict):
        """Process a single decoded TETRA JSON frame."""
        frame["_ts"] = time.time()

        # Broadcast to all WebSocket clients
        dead = set()
        msg = json.dumps(frame)
        for ws in ws_clients:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        ws_clients -= dead

        # Persist to database
        if _db_callback:
            try:
                await _db_callback(frame)
            except Exception as e:
                logger.error(f"DB callback error: {e}")


async def start_udp_listener(port: int = 42100):
    """Start listening for tetra-kit decoder JSON output."""
    loop = asyncio.get_event_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        TetraUDPProtocol,
        local_addr=("0.0.0.0", port),
    )
    logger.info(f"Listening for tetra-kit JSON on UDP port {port}")
    return transport


class AudioUDPProtocol(asyncio.DatagramProtocol):
    """Receive 16-bit PCM audio from GNU Radio on UDP 42002 and broadcast to WebSocket clients."""

    def datagram_received(self, data: bytes, addr):
        dead = set()
        for ws in audio_ws_clients:
            try:
                asyncio.ensure_future(ws.send_bytes(data))
            except Exception:
                dead.add(ws)
        audio_ws_clients.difference_update(dead)


async def start_audio_listener(port: int = 42002):
    """Start listening for audio PCM stream."""
    loop = asyncio.get_event_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        AudioUDPProtocol,
        local_addr=("0.0.0.0", port),
    )
    logger.info(f"Listening for audio PCM on UDP port {port}")
    return transport


class FFTUDPProtocol(asyncio.DatagramProtocol):
    """Receive FFT power spectrum (256 x float32) from GNU Radio on UDP 42003
    and broadcast raw binary to WebSocket clients."""

    def datagram_received(self, data: bytes, addr):
        if not fft_ws_clients:
            return
        dead = set()
        for ws in fft_ws_clients:
            try:
                asyncio.ensure_future(ws.send_bytes(data))
            except Exception:
                dead.add(ws)
        fft_ws_clients.difference_update(dead)


async def start_fft_listener(port: int = 42003):
    """Start listening for FFT spectrum data."""
    loop = asyncio.get_event_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        FFTUDPProtocol,
        local_addr=("0.0.0.0", port),
    )
    logger.info(f"Listening for FFT spectrum on UDP port {port}")
    return transport
