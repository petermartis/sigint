# Sigint — Autonomous Radio Scanner & Decoder

**Sigint** is a full-stack software-defined radio (SDR) scanner and protocol decoder built for the Raspberry Pi. It combines an RTL-SDR receiver with GNU Radio signal processing, protocol-specific decoders, a frequency scanner, and a real-time web dashboard for monitoring, analysis, and recording of radio communications.

## Table of Contents

- [System Overview](#system-overview)
- [Supported Protocols](#supported-protocols)
- [Hardware Requirements](#hardware-requirements)
- [Architecture](#architecture)
- [Installation](#installation)
- [Configuration](#configuration)
- [Web UI Guide](#web-ui-guide)
- [REST API Reference](#rest-api-reference)
- [Frequency Scanner](#frequency-scanner)
- [WebSocket Streams](#websocket-streams)
- [Service Management](#service-management)
- [Troubleshooting](#troubleshooting)

---

## System Overview

Sigint operates as three coordinated services on the Raspberry Pi:

1. **tetra-sdr** — GNU Radio flowgraph that captures RF via RTL-SDR, demodulates, and outputs symbol/audio/FFT data over UDP.
2. **tetra-decoder** — tetra-kit process that decodes TETRA protocol frames from demodulated symbols.
3. **tetra-api** — FastAPI server providing REST endpoints, WebSocket streams, SQLite persistence, and the web UI.

The system supports 7 demodulation modes switchable at runtime without restarting services, and includes a built-in frequency scanner that automatically steps through saved channels, stopping on active signals.

---

## Supported Protocols

### TETRA (Terrestrial Trunked Radio)

| Parameter | Value |
|---|---|
| **Standard** | ETSI EN 300 392 / EN 300 396 |
| **Modulation** | π/4-DQPSK (Differential Quadrature Phase Shift Keying) |
| **Channel spacing** | 25 kHz |
| **Symbol rate** | 18,000 symbols/sec |
| **Duplex** | TDMA, 4 timeslots per carrier |
| **Frequency bands** | 380–400 MHz (emergency), 410–430 MHz, 450–470 MHz, 870–876 / 915–921 MHz |
| **Demod gain** | 1.0 (phase demodulator) |

**Description:**
TETRA is the dominant European standard for mission-critical professional mobile radio (PMR). It provides trunked voice, data, and short messaging (SDS) services with optional end-to-end encryption (TEA1–TEA3 algorithms). TETRA's TDMA structure carries 4 independent traffic channels per 25 kHz RF carrier.

**Typical users:** Emergency services (police, fire, ambulance), military, public transport operators, utilities, airport ground operations. Deployed as national networks in most European countries (e.g., VIRVE in Finland, C2000 in the Netherlands, Airwave/ESN in the UK, RAKEL in Sweden, BOS in Germany).

**Decoder:** tetra-kit provides full Layer 2/3 decoding, including system info broadcasts, call setup/release, SDS messages, and voice frame extraction (ACELP codec).

---

### DMR (Digital Mobile Radio)

| Parameter | Value |
|---|---|
| **Standard** | ETSI TS 102 361 |
| **Modulation** | 4FSK (4-level Frequency Shift Keying) |
| **Channel spacing** | 12.5 kHz |
| **Symbol rate** | 4,800 baud |
| **Deviation** | ±1.944 kHz (outer), ±648 Hz (inner) |
| **Duplex** | 2-slot TDMA |
| **Frequency bands** | VHF (136–174 MHz), UHF (400–527 MHz) |
| **Demod gain** | ≈2.95 (channel_rate / 2π × 1944 Hz) |

**Description:**
DMR is an open digital radio standard designed as a direct replacement for analog FM PMR systems. It operates in three tiers: Tier I (unlicensed, 446 MHz), Tier II (conventional licensed), and Tier III (trunked). DMR's 2-slot TDMA doubles channel capacity versus analog by carrying two simultaneous voice or data conversations on a single 12.5 kHz carrier. Uses AMBE+2 vocoder for voice compression.

**Typical users:** Commercial fleet operators, security companies, construction sites, hospitality, manufacturing, amateur radio (via DMR-MARC and Brandmeister networks). Major manufacturers include Motorola (MOTOTRBO), Hytera, Tait, and Kenwood.

**Decoder status:** Quadrature demodulation only (raw discriminator audio). Full protocol decoding would require DSD+ or similar frame-sync + vocoder software.

---

### P25 (Project 25 / APCO-25)

| Parameter | Value |
|---|---|
| **Standard** | TIA-102 (APCO Project 25) |
| **Modulation** | Phase 1: C4FM (Continuous 4-level FM); Phase 2: H-DQPSK |
| **Channel spacing** | Phase 1: 12.5 kHz; Phase 2: 6.25 kHz equivalent (2-slot TDMA on 12.5 kHz) |
| **Symbol rate** | 4,800 baud |
| **Deviation** | ±1.8 kHz (outer), ±600 Hz (inner) |
| **Frequency bands** | VHF (136–174 MHz), UHF (380–512 MHz), 700 MHz, 800 MHz (806–869 MHz) |
| **Demod gain** | ≈3.18 (channel_rate / 2π × 1800 Hz) |

**Description:**
P25 is the North American public safety digital radio standard, developed under the Association of Public-Safety Communications Officials (APCO). Phase 1 uses FDMA with C4FM modulation and the IMBE vocoder. Phase 2 adds TDMA for improved spectral efficiency and uses the AMBE+2 vocoder. P25 supports over-the-air encryption (DES, AES-256), over-the-air rekeying (OTAR), and inter-system roaming via ISSI (Inter-RF Subsystem Interface).

**Typical users:** US and Canadian law enforcement, fire departments, EMS, federal agencies (FBI, DHS, FEMA, Secret Service), state/county governments, some international deployments (Australia, New Zealand, Latin America). Major systems include Harris (L3Harris), Motorola APX series, and EF Johnson.

**Decoder status:** Quadrature demodulation only. Full decoding requires OP25 or DSD+ for frame synchronization, trunking control channel following, and IMBE/AMBE+2 vocoder decoding.

---

### NXDN (Next Generation Digital Narrowband)

| Parameter | Value |
|---|---|
| **Standard** | NXDN Forum Technical Specifications (jointly developed by Kenwood and Icom) |
| **Modulation** | 4FSK |
| **Channel spacing** | 6.25 kHz (narrow) or 12.5 kHz (wide) |
| **Symbol rate** | 2,400 baud (6.25 kHz) or 4,800 baud (12.5 kHz) |
| **Deviation** | ±1.05 kHz (6.25 kHz mode), ±2.4 kHz (12.5 kHz mode) |
| **Frequency bands** | VHF (136–174 MHz), UHF (400–520 MHz) |
| **Demod gain** | ≈2.39 (channel_rate / 2π × 2400 Hz, wide mode) |

**Description:**
NXDN achieves ultra-narrowband operation at 6.25 kHz channel spacing — half the bandwidth of DMR or P25 Phase 1 — enabling maximum spectrum efficiency. It supports both conventional and trunked modes, with Type-C and Type-D trunking providing automatic channel assignment. Voice is encoded using the AMBE+2 vocoder. NXDN defines two air interface variants: NEXEDGE (Kenwood's branding) and IDAS (Icom's branding), which are interoperable at the air interface level.

**Typical users:** Small-to-medium enterprises, property management, education campuses, hospitality, municipal government, healthcare facilities. Popular in markets where spectrum is scarce (Japan, parts of Europe and Asia). Kenwood NEXEDGE and Icom IDAS are the primary product lines.

**Decoder status:** Quadrature demodulation only. Full decoding would require DSD+ or dedicated NXDN decoder software.

---

### dPMR (Digital Private Mobile Radio)

| Parameter | Value |
|---|---|
| **Standard** | ETSI TS 102 658 |
| **Modulation** | 4FSK |
| **Channel spacing** | 6.25 kHz |
| **Symbol rate** | 2,400 baud |
| **Deviation** | ±1.05 kHz |
| **Frequency bands** | VHF (136–174 MHz), UHF (400–527 MHz), 446 MHz (licence-free) |
| **Demod gain** | ≈5.46 (channel_rate / 2π × 1050 Hz) |

**Description:**
dPMR is the ETSI-standardized counterpart to DMR, designed for 6.25 kHz narrowband operation. It operates in three modes: Mode 1 (peer-to-peer, licence-free at 446 MHz), Mode 2 (conventional repeater), and Mode 3 (trunked). dPMR uses AMBE+2 for voice and supports basic encryption. Its 6.25 kHz channel spacing makes it particularly spectrum-efficient, fitting 4 channels in the same bandwidth as a single analog FM channel.

**Typical users:** Light commercial users, small businesses, retail, warehousing, licence-free consumer radio users (dPMR446). Manufacturers include Kenwood, Icom, and several Chinese manufacturers. Most popular in Europe and Asia where 6.25 kHz channelisation aligns with regional spectrum plans.

**Decoder status:** Quadrature demodulation only. Full decoding would require DSD+ or similar software.

---

### Analog FM (Frequency Modulation)

| Parameter | Value |
|---|---|
| **Modulation** | Narrowband FM (NBFM) |
| **Channel spacing** | 12.5 kHz or 25 kHz |
| **Deviation** | ±5 kHz (wideband) or ±2.5 kHz (narrowband) |
| **Frequency bands** | Any within RTL-SDR range (24 MHz – 1.766 GHz) |
| **Demod gain** | ≈1.15 (channel_rate / 2π × 5000 Hz) |

**Description:**
Conventional analog FM remains the most widely used modulation for land mobile radio (LMR). NBFM at ±5 kHz deviation on 25 kHz channels (or ±2.5 kHz on 12.5 kHz channels) covers everything from amateur radio repeaters to legacy commercial dispatch systems. Sigint's FM demodulator uses a standard quadrature discriminator optimized for narrowband PMR voice.

**Typical users:** Amateur radio (VHF/UHF repeaters), legacy PMR446, FRS/GMRS (North America), marine VHF, aviation ground support, older commercial two-way radio systems.

---

### Analog AM (Amplitude Modulation)

| Parameter | Value |
|---|---|
| **Modulation** | Double-sideband AM (DSB-AM), envelope detection |
| **Channel spacing** | 8.33 kHz (aviation) or 25 kHz |
| **Frequency bands** | HF, VHF airband (108–137 MHz), UHF |
| **Demod method** | Complex-to-magnitude (envelope detector) |

**Description:**
AM demodulation via envelope detection (complex-to-magnitude) is used primarily for monitoring aviation communications. The VHF airband (108–137 MHz) uses DSB-AM exclusively due to its superior intelligibility in high-noise cockpit environments and compatibility with decades of installed equipment. Sigint uses a simple magnitude detector followed by DC-removal gain staging.

**Typical users:** Civil aviation (tower, approach, ground, ATIS, VOLMET), military aviation (UHF AM at 225–400 MHz), HF communications, AM broadcast monitoring.

---

## Hardware Requirements

- **Raspberry Pi 5** (4 GB+ RAM, aarch64) — also runs on RPi 3/4 (armv7l/aarch64)
- **RTL-SDR USB dongle** (RTL2832U + R820T2/FC0013/E4000 tuner)
  - Supported frequency range: 24 MHz – 1.766 GHz
  - ADC: 8-bit, up to 3.2 MS/s
- **Antenna** appropriate for target frequency band
- **MicroSD card** ≥ 16 GB (Class 10 or better)
- **Power supply**: 5V / 3A (5A for RPi5 with peripherals)
- **Network**: Ethernet or WiFi for web UI access

---

## Architecture

### Data Flow

```
RTL-SDR USB → GNU Radio Flowgraph → Demodulator → UDP Streams → API Server → WebSocket → Browser
                    ↓                                              ↓
              FFT Probe → UDP 42003                          SQLite DB
                    ↓
             XML-RPC :42001 (tuning control)
```

### File Layout (on Raspberry Pi)

```
/opt/tetra-scanner/
├── bin/
│   └── tetra_rx_headless.py      # GNU Radio SDR flowgraph
├── api/
│   ├── main.py                   # FastAPI server (+ scan engine)
│   ├── ingestor.py               # UDP → WebSocket bridge
│   └── database.py               # SQLite schema & helpers
├── web/
│   └── index.html                # Sigint dashboard (single-file SPA)
├── etc/
│   ├── tetra-scanner.conf        # Runtime configuration
│   └── scan-list.json            # Saved scan channels & config (auto-created)
├── data/
│   └── tetra_scanner.db          # SQLite database
└── recordings/                   # Saved audio files
```

### UDP Port Map

| Port | Direction | Payload | Purpose |
|------|-----------|---------|---------|
| 42000 | GR → tetra-kit | Float32 symbols | Demodulated TETRA symbols |
| 42001 | API → GR | XML-RPC | Runtime tuning (freq, gain, ppm, mode) |
| 42002 | GR → API | Int16 PCM @ 16 kHz | Live audio monitoring stream |
| 42003 | GR → API | 256 × Float32 | FFT power spectrum (dB) @ 15 fps |
| 42100 | tetra-kit → API | JSON text | Decoded TETRA protocol frames |

### GNU Radio Flowgraph

```
RTL-SDR Source (2 MS/s)
    ├── freq_xlating_fir_filter (decimate to 36 kHz channel)
    │   └── [Demodulator — mode-dependent]
    │       ├── TETRA:  quadrature_demod_cf (gain=1.0) → UDP :42000
    │       ├── DMR:    quadrature_demod_cf (gain=2.95)
    │       ├── P25:    quadrature_demod_cf (gain=3.18)
    │       ├── NXDN:   quadrature_demod_cf (gain=2.39)
    │       ├── dPMR:   quadrature_demod_cf (gain=5.46)
    │       ├── FM:     quadrature_demod_cf (gain=1.15)
    │       └── AM:     complex_to_mag → multiply_const_ff
    │       └── [all] → rational_resampler (36k→16k) → float_to_short → UDP :42002
    │
    └── stream_to_vector (256) → probe_signal_vc
        └── [Python thread: numpy FFT @ 15fps → UDP :42003]
```

Mode switching uses `top_block.lock()` / `disconnect_all()` / reconnect / `unlock()` for glitch-free runtime reconfiguration.

### Systemd Services

| Service | Binary | Description |
|---------|--------|-------------|
| `tetra-sdr` | `tetra_rx_headless.py` | GNU Radio flowgraph (RTL-SDR → demod → UDP) |
| `tetra-decoder` | `tetra-kit` | TETRA protocol decoder (UDP 42000 → JSON → UDP 42100) |
| `tetra-api` | `uvicorn main:app` | FastAPI server (REST + WebSocket + static UI on port 80) |

---

## Installation

### Prerequisites

```bash
# System packages (Debian trixie / bookworm)
sudo apt-get update && sudo apt-get install -y \
    build-essential cmake git python3-pip python3-venv python3-numpy \
    libusb-1.0-0-dev librtlsdr-dev rapidjson-dev

# GNU Radio 3.10 + RTL-SDR support
sudo apt-get install -y gnuradio gr-osmosdr rtl-sdr
```

### RTL-SDR Setup

```bash
# Blacklist kernel DVB-T driver (conflicts with SDR use)
echo 'blacklist dvb_usb_rtl28xxu' | sudo tee /etc/modprobe.d/blacklist-rtlsdr.conf
sudo modprobe -r dvb_usb_rtl28xxu

# Verify device detection
rtl_test -t
```

### tetra-kit Decoder

```bash
# Clone into the source tree
git clone https://github.com/AidasDir/tetra-kit.git /opt/tetra-scanner/src/tetra-kit
cd /opt/tetra-scanner/src/tetra-kit && bash build.sh

# Install binaries
cp decoder/decoder /opt/tetra-scanner/bin/tetra-decoder
cp recorder/recorder /opt/tetra-scanner/bin/tetra-recorder
cp codec/cdecoder /opt/tetra-scanner/bin/tetra-cdecoder
cp codec/sdecoder /opt/tetra-scanner/bin/tetra-sdecoder
chmod +x /opt/tetra-scanner/bin/tetra-*
```

### Deploy Sigint

```bash
# Create directory structure
sudo mkdir -p /opt/tetra-scanner/{bin,api,web,etc,data,recordings,logs,src}
sudo chown -R $USER:$USER /opt/tetra-scanner

# Copy application files
cp tetra_rx_headless.py /opt/tetra-scanner/bin/
cp sigint-api-main.py /opt/tetra-scanner/api/main.py
cp sigint-ingestor.py /opt/tetra-scanner/api/ingestor.py
cp sigint-ui.html /opt/tetra-scanner/web/index.html

# Create Python virtual environment for the API server
python3 -m venv /opt/tetra-scanner/venv
/opt/tetra-scanner/venv/bin/pip install fastapi uvicorn aiosqlite websockets
```

### Configuration File

Create `/opt/tetra-scanner/etc/tetra-scanner.conf`:

```bash
# TETRA Scanner Configuration
TETRA_FREQ=390525000
TETRA_GAIN=40
TETRA_PPM=0
TETRA_SAMP_RATE=2000000
TETRA_DECODER_PORT_IN=42000
TETRA_DECODER_PORT_OUT=42100
TETRA_API_HOST=0.0.0.0
TETRA_API_PORT=80
TETRA_DB_PATH=/opt/tetra-scanner/data/tetra.db
TETRA_RECORDINGS_DIR=/opt/tetra-scanner/recordings
```

### Systemd Service Files

**tetra-sdr.service:**
```ini
[Unit]
Description=TETRA SDR Receiver (GNU Radio headless)
After=network.target
Wants=tetra-decoder.service

[Service]
Type=simple
User=admin
EnvironmentFile=/opt/tetra-scanner/etc/tetra-scanner.conf
ExecStart=/usr/bin/python3 /opt/tetra-scanner/bin/tetra_rx_headless.py --freq ${TETRA_FREQ} --gain ${TETRA_GAIN} --ppm ${TETRA_PPM} --samp-rate ${TETRA_SAMP_RATE}
Restart=always
RestartSec=5
StandardOutput=append:/opt/tetra-scanner/logs/sdr.log
StandardError=append:/opt/tetra-scanner/logs/sdr.log

[Install]
WantedBy=multi-user.target
```

**tetra-decoder.service:**
```ini
[Unit]
Description=TETRA-Kit Decoder Pipeline
After=network.target
Wants=tetra-api.service

[Service]
Type=simple
User=admin
EnvironmentFile=/opt/tetra-scanner/etc/tetra-scanner.conf
ExecStart=/opt/tetra-scanner/bin/tetra-decoder -r udp:${TETRA_DECODER_PORT_IN} -t udp:127.0.0.1:${TETRA_DECODER_PORT_OUT} -w
Restart=always
RestartSec=3
StandardOutput=append:/opt/tetra-scanner/logs/decoder.log
StandardError=append:/opt/tetra-scanner/logs/decoder.log

[Install]
WantedBy=multi-user.target
```

**tetra-api.service:**
```ini
[Unit]
Description=TETRA Scanner API Server
After=network.target

[Service]
Type=simple
User=admin
EnvironmentFile=/opt/tetra-scanner/etc/tetra-scanner.conf
WorkingDirectory=/opt/tetra-scanner/api
ExecStart=/opt/tetra-scanner/venv/bin/uvicorn main:app --host ${TETRA_API_HOST} --port ${TETRA_API_PORT} --log-level info
AmbientCapabilities=CAP_NET_BIND_SERVICE
Restart=always
RestartSec=3
StandardOutput=append:/opt/tetra-scanner/logs/api.log
StandardError=append:/opt/tetra-scanner/logs/api.log

[Install]
WantedBy=multi-user.target
```

```bash
# Install, enable, and start
sudo cp tetra-sdr.service tetra-decoder.service tetra-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable tetra-sdr tetra-decoder tetra-api
sudo systemctl start tetra-sdr tetra-decoder tetra-api
```

---

## Configuration

### Runtime Configuration (`/opt/tetra-scanner/etc/tetra-scanner.conf`)

Key parameters are controlled at runtime via XML-RPC (port 42001) and the web UI:

- **Center Frequency** — 24 MHz to 1.766 GHz
- **RF Gain** — 0 (auto) to 49 dB
- **PPM Correction** — Frequency offset compensation for crystal drift
- **Demodulation Mode** — One of: `tetra`, `dmr`, `p25`, `nxdn`, `dpmr`, `analog_fm`, `analog_am`

### Command-Line Options (tetra_rx_headless.py)

```
--freq, -f    Center frequency in Hz (required)      e.g. 390.525e6
--gain, -g    RF gain in dB (default: 40)
--ppm, -p     Frequency correction in PPM (default: 0)
--samp-rate   Sample rate (default: 2e6)
--rpc-port    XML-RPC control port (default: 42001)
```

---

## Web UI Guide

Access the dashboard at `http://<raspberry-pi-ip>/` (port 80)

### Top Bar

- **Connection indicator** — Green dot = connected, red = disconnected
- **Frequency display** — Click to retune; enter new frequency in MHz
- **Mode selector** — Dropdown to switch demodulation protocol (TETRA / DMR / P25 / NXDN / dPMR / FM / AM)
- **+ CH** — Quick-save the current frequency and mode as a scan channel. Opens a small popover where you can name the channel, then press Enter or click Save. A toast notification confirms the save.
- **Scan** — Start/stop the frequency scanner. When scanning, the button pulses amber and shows "Stop". Turns green when dwelling on an active signal. If no channels are saved, shows a toast hint.
- **Skip** — Appears during scanning; advances to the next channel immediately.
- **Scan indicator** — Shows the current channel label and signal level during scanning.
- **Pause / Clear / Record** — Control event stream capture and audio recording
- **Settings gear** — Open full settings panel

### Spectrum & Waterfall

- **Spectrum analyzer** — Real-time FFT power display (256-point, 15 fps), calibrated in dBm
- **Waterfall** — Scrolling spectrogram with configurable colormap (Green, Viridis, Magma, Inferno, Plasma, Turbo)
- **Signal meter** — Bar graph + numeric dB readout of center channel power

### Event Stream

- **Live feed** — Decoded protocol events in real time
- **Filter tabs** — All / Calls / SDS / Voice / System
- **Event cards** — Color-coded by type, showing timestamp, type badge, and decoded content
- **Adaptive layout** — Automatically hidden for non-TETRA modes (FM, AM, DMR, P25, NXDN, dPMR) since they have no protocol decoder; spectrum + waterfall expand to fill the full panel height

### Right Panel

- **Statistics** — Live counters for frames, calls, messages, connected clients
- **Active Calls** — Currently active voice/data calls with SSI identifiers
- **Recordings** — List of saved audio files with playback controls
- **Audio Monitor** — Waveform display with play/pause, powered by WebSocket PCM stream

### Settings Panel

Seven configuration sections:

1. **Receiver** — Frequency, gain, PPM, sample rate, AGC, DC offset, bias tee
2. **Decoder** — Protocol selection, timeslot filter, FEC, voice/SDS decoding toggles
3. **Scanner** — Scan list editor (label, frequency, mode, squelch, lockout per channel), default squelch slider, dwell time, hysteresis, settle time. Channels can also be added quickly from the topbar `+ CH` button.
4. **Display** — Spectrum color, peak hold, grid lines, dB scale, waterfall colormap/speed, max events
5. **Storage** — Recording directory, format (WAV/FLAC/OGG), auto-record, retention limits
6. **Connection** — API host, WebSocket reconnect, polling intervals
7. **System** — Service restart controls, log viewer, database management

---

## REST API Reference

Base URL: `http://<host>`

### GET /api/status

System overview with aggregate counts.

**Response:**
```json
{
  "total_events": 15234,
  "total_calls": 89,
  "total_sds": 12,
  "last_event_ts": 1709142000.123,
  "ws_clients": 2,
  "uptime": 1709142000.0
}
```

### GET /api/radio

Current SDR state.

**Response:**
```json
{
  "frequency": 390525000.0,
  "gain": 40.0,
  "ppm": 0.0,
  "mode": "tetra"
}
```

### POST /api/tune

Retune SDR parameters. All fields optional.

**Request:**
```json
{
  "frequency": 390525000.0,
  "gain": 35.0,
  "ppm": 1.5
}
```

### POST /api/mode

Switch demodulation mode.

**Request:**
```json
{ "mode": "dmr" }
```

**Valid modes:** `tetra`, `dmr`, `p25`, `nxdn`, `dpmr`, `analog_fm`, `analog_am`

### GET /api/events

Query decoded events from the database.

**Parameters:**
- `limit` (int, 1–1000, default 100)
- `offset` (int, default 0)
- `event_type` (string, optional filter)
- `since` (float, Unix timestamp, optional)

### GET /api/calls

Query call records. Parameters: `limit`, `offset`, `since`.

### GET /api/sds

Query SDS (Short Data Service) messages. Parameters: `limit`, `offset`.

### GET /api/recordings

List available audio recordings.

### GET /api/recordings/{filename}

Download a specific recording file.

---

## Frequency Scanner

Sigint includes a built-in frequency scanner that cycles through a user-defined channel list, automatically stopping on active signals. The scanner operates as an async task in the API server, retuning the SDR via XML-RPC and reading signal levels from the GNU Radio FFT probe.

### Workflow

1. **Save channels** — Tune to a frequency, click **+ CH** in the topbar, name it, press Enter. Repeat for all frequencies of interest.
2. **Start scanning** — Click **Scan** in the topbar. The scanner steps through saved channels.
3. **Signal detection** — When signal power exceeds the squelch threshold, the scanner stops and dwells on that channel.
4. **Auto-resume** — When the signal drops below the threshold (minus hysteresis) for longer than the dwell time, scanning resumes.
5. **Skip / Lockout** — Click **Skip** to advance manually. Toggle **Lockout** in Settings → Scanner to permanently skip a channel.

### Scan Algorithm

```
for each channel (skipping locked-out entries):
    retune SDR to channel frequency
    switch mode if channel specifies one
    wait settle_time (150ms default)
    read signal level from FFT probe
    if signal_level > squelch_threshold:
        DWELL: hold on frequency, broadcast "hit" to UI
        poll signal level every 300ms
        when signal < (squelch - hysteresis):
            wait dwell_time (2s default)
            resume scanning
    advance to next channel
```

### Scan Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| **Squelch** | -50 dB | Signal power threshold to stop scanning |
| **Dwell** | 2.0 sec | Hold time after signal lost before resuming |
| **Hysteresis** | 6 dB | Below squelch to declare signal truly gone |
| **Settle** | 150 ms | Wait after retune before reading signal level |

Configurable in Settings → Scanner, or via `POST /api/scan/config`.

### Scan Channel Storage

Channels are persisted to `/opt/tetra-scanner/etc/scan-list.json` (auto-created on first save). Each entry stores:

- `id` — Unique 8-character identifier
- `label` — User-defined name (e.g., "POLICE", "FIRE")
- `frequency` — Center frequency in Hz
- `mode` — Demodulation mode (null = keep current mode)
- `squelch` — Per-channel squelch override (dB)
- `locked_out` — Skip during scanning (boolean)

### Scan API Endpoints

#### GET /api/scan/list

Return all scan entries and config.

**Response:**
```json
{
  "entries": [
    {"id": "a1b2c3d4", "label": "POLICE", "frequency": 390525000, "mode": "tetra", "squelch": -50, "locked_out": false}
  ],
  "config": {"squelch": -50, "dwell": 2.0, "hysteresis": 6, "settle": 0.15}
}
```

#### POST /api/scan/list

Add a new scan entry.

**Request:**
```json
{"label": "FIRE", "frequency": 391050000, "mode": "tetra", "squelch": -45}
```

#### PUT /api/scan/list/{id}

Update an existing entry. Body may contain any subset of: `label`, `frequency`, `mode`, `squelch`, `locked_out`.

#### DELETE /api/scan/list/{id}

Remove a scan entry.

#### POST /api/scan/config

Update scan settings.

**Request:**
```json
{"squelch": -45, "dwell": 3.0, "hysteresis": 8, "settle": 0.2}
```

#### POST /api/scan/start

Start the scan loop. Returns 400 if the scan list is empty.

#### POST /api/scan/stop

Stop the scan loop.

#### GET /api/scan/status

Current scan state.

**Response:**
```json
{
  "active": true,
  "dwelling": false,
  "index": 2,
  "entry": {"id": "a1b2c3d4", "label": "POLICE", "frequency": 390525000, ...},
  "signal_level": -62.3,
  "config": {"squelch": -50, "dwell": 2.0, ...},
  "total": 5
}
```

#### POST /api/scan/skip

Skip to the next channel during scanning.

#### POST /api/scan/lockout/{id}

Toggle lockout on a scan entry.

---

## WebSocket Streams

### /ws — Event Stream

JSON text frames containing decoded protocol events. Each frame includes a `_ts` field (Unix timestamp) added by the ingestor.

### /ws/audio — Live Audio

Binary frames of 16-bit signed PCM audio at 16 kHz sample rate. Audio is resampled from the 36 kHz channel rate (interpolation=4, decimation=9) and scaled by gain factor 8000.

### /ws/fft — Spectrum Data

Binary frames of 256 × float32 values representing FFT power spectrum in dB. Data arrives at ~15 fps. The UI performs FFT-shift (swap halves) to center DC. Calibrated with -80 dB offset for realistic spectrum analyzer readings.

### Scan Events (via /ws)

When the frequency scanner is running, scan state changes are broadcast as JSON text frames on the main `/ws` endpoint. These messages have `"_scan": true` and an `action` field:

- `{"_scan": true, "action": "started"}` — Scan loop began
- `{"_scan": true, "action": "hit", "entry": {...}, "level": -42.3}` — Signal detected, dwelling
- `{"_scan": true, "action": "dwell", "entry": {...}}` — Signal lost, post-dwell countdown
- `{"_scan": true, "action": "resume"}` — Resuming scan after dwell
- `{"_scan": true, "action": "stopped"}` — Scan loop ended

The UI distinguishes scan messages from decoded protocol frames via the `_scan` field.

---

## Service Management

### Starting / Stopping

```bash
sudo systemctl start tetra-sdr tetra-api tetra-decoder
sudo systemctl stop tetra-sdr tetra-api tetra-decoder
```

### Restarting After Code Changes

```bash
# Deploy updated files (replace IP with your RPi address)
scp tetra_rx_headless.py admin@192.168.3.217:/opt/tetra-scanner/bin/
scp sigint-api-main.py admin@192.168.3.217:/opt/tetra-scanner/api/main.py
scp sigint-ingestor.py admin@192.168.3.217:/opt/tetra-scanner/api/ingestor.py
scp sigint-ui.html admin@192.168.3.217:/opt/tetra-scanner/web/index.html

# Restart services
ssh admin@192.168.3.217 'sudo systemctl restart tetra-sdr tetra-api'
```

Note: The scan channel list (`/opt/tetra-scanner/etc/scan-list.json`) is auto-created when you first save a channel from the UI. It persists across service restarts.

### Viewing Logs

Service logs are written to `/opt/tetra-scanner/logs/`:

```bash
tail -f /opt/tetra-scanner/logs/sdr.log
tail -f /opt/tetra-scanner/logs/api.log
tail -f /opt/tetra-scanner/logs/decoder.log
```

Or via journalctl:

```bash
journalctl -u tetra-sdr -f
journalctl -u tetra-api -f
journalctl -u tetra-decoder -f
```

### Shared Memory Cleanup

After restarting `tetra-sdr`, stale GNU Radio shared memory segments may remain:

```bash
ipcs -m | grep admin | awk '{print $2}' | xargs -I{} ipcrm -m {}
```

---

## Troubleshooting

### RTL-SDR not detected

- Ensure the kernel DVB-T driver is blacklisted: `lsmod | grep dvb`
- Check USB connection: `lsusb` should show the RTL2832U device
- Run `rtl_test -t` to verify tuner access

### No spectrum / audio after mode switch

- Shared memory may be stale. Run the cleanup command above.
- Check `journalctl -u tetra-sdr -f` for GNU Radio errors.
- The `lock()`/`unlock()` mechanism can occasionally deadlock under heavy load; restart `tetra-sdr` if needed.

### WebSocket disconnects frequently

- Check RPi network stability. Wired Ethernet is more reliable than WiFi.
- The API server auto-cleans dead WebSocket connections on next broadcast.

### High CPU usage

- FFT computation runs at 15 fps with 256-point FFT — lightweight on RPi5, but can add up on RPi3.
- Reduce FFT rate by editing the `time.sleep(1.0 / 15)` interval in `tetra_rx_headless.py`.
- Ensure sample rate is 2 MS/s; higher rates increase CPU load significantly.

### Database grows too large

- Events accumulate in `/opt/tetra-scanner/data/tetra_scanner.db`.
- Periodically purge old events: `sqlite3 tetra_scanner.db "DELETE FROM events WHERE ts < strftime('%s','now','-7 days')"`
- Configure retention in the Settings → Storage panel.

### "Cannot open RTL-SDR device" error

- Only one process can access the RTL-SDR at a time.
- Check for zombie processes: `ps aux | grep rtl`
- Kill any stale processes and restart `tetra-sdr`.

---

## License

This project is provided as-is for educational and research purposes.
