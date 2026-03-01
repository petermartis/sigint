#!/usr/bin/env python3
"""Headless GNU Radio TETRA PI/4-DQPSK receiver for tetra-kit.

Receives RF via RTL-SDR, demodulates PI/4-DQPSK, sends symbols
to tetra-kit decoder via UDP port 42000.

Exposes XML-RPC control on port 42001 for runtime tuning.

Usage: tetra_rx_headless.py --freq <Hz> [--gain <dB>] [--ppm <ppm>]
"""

import argparse
import signal
import sys
import threading
from xmlrpc.server import SimpleXMLRPCServer

import struct
import socket
import numpy as np

from gnuradio import gr, blocks, analog, digital, filter as grfilter, network, fft
from gnuradio.filter import firdes
from gnuradio.fft import window
import osmosdr


# Valid modes and their labels
MODES = ['tetra', 'dmr', 'p25', 'nxdn', 'dpmr', 'analog_fm', 'analog_am']


class TetraReceiver(gr.top_block):
    def __init__(self, freq, gain=40, ppm=0, samp_rate=2e6):
        gr.top_block.__init__(self, "TETRA Headless Receiver")

        self.samp_rate = samp_rate
        self.freq = freq
        self.gain = gain
        self.ppm = ppm
        self.channel_rate = 36000
        self.mode = 'tetra'

        # RTL-SDR source
        self.src = osmosdr.source(args="numchan=1 rtl=0")
        self.src.set_sample_rate(self.samp_rate)
        self.src.set_center_freq(self.freq, 0)
        self.src.set_freq_corr(ppm, 0)
        self.src.set_gain(self.gain, 0)
        self.src.set_if_gain(20, 0)
        self.src.set_bb_gain(20, 0)
        self.src.set_bandwidth(0, 0)

        # Low-pass filter + decimation to ~36 kHz channel
        decimation = int(self.samp_rate / self.channel_rate)
        self.lpf = grfilter.freq_xlating_fir_filter_ccc(
            decimation,
            firdes.low_pass(1, self.samp_rate, 18000, 5000, window.WIN_HAMMING),
            0,
            self.samp_rate,
        )

        # ── Demodulators (pre-created for runtime switching) ──

        # TETRA: PI/4-DQPSK phase demod
        self.demod_tetra = analog.quadrature_demod_cf(1.0)

        # Analog FM: quadrature demod, gain = channel_rate / (2π × deviation)
        # NBFM deviation ~5 kHz → gain ≈ 36000 / (2π × 5000) ≈ 1.15
        self.demod_fm = analog.quadrature_demod_cf(
            self.channel_rate / (2.0 * 3.14159 * 5000)
        )

        # DMR: 4FSK, 12.5 kHz channel, ±1.944 kHz deviation per symbol level
        # gain = channel_rate / (2π × peak_deviation) ≈ 36000 / (2π × 1944) ≈ 2.95
        self.demod_dmr = analog.quadrature_demod_cf(
            self.channel_rate / (2.0 * 3.14159 * 1944)
        )

        # P25: C4FM, 12.5 kHz channel, ±1.8 kHz deviation
        # gain ≈ 36000 / (2π × 1800) ≈ 3.18
        self.demod_p25 = analog.quadrature_demod_cf(
            self.channel_rate / (2.0 * 3.14159 * 1800)
        )

        # NXDN: 4FSK, 12.5 kHz channel, ±2.4 kHz deviation (wide mode)
        # gain ≈ 36000 / (2π × 2400) ≈ 2.39
        self.demod_nxdn = analog.quadrature_demod_cf(
            self.channel_rate / (2.0 * 3.14159 * 2400)
        )

        # dPMR: 4FSK, 6.25 kHz channel, ±1.05 kHz deviation
        # gain ≈ 36000 / (2π × 1050) ≈ 5.46
        self.demod_dpmr = analog.quadrature_demod_cf(
            self.channel_rate / (2.0 * 3.14159 * 1050)
        )

        # Analog AM: envelope detector (complex → magnitude)
        self.demod_am_mag = blocks.complex_to_mag(1)
        self.demod_am_dc = blocks.multiply_const_ff(1.0)  # placeholder for DC removal

        # Null sink to absorb tetra-kit UDP output when not in TETRA mode
        self.null_float = blocks.null_sink(gr.sizeof_float)

        # UDP sink to tetra-kit decoder (port 42000) — active only in TETRA mode
        self.udp_sink = network.udp_sink(
            gr.sizeof_float, 1, "127.0.0.1", 42000, 0, 1472, True
        )

        # Audio monitoring path: demod float → resample 36k→16k → 16-bit PCM → UDP
        self.audio_resamp = grfilter.rational_resampler_fff(
            interpolation=4, decimation=9,
        )
        self.audio_gain = blocks.multiply_const_ff(8000)  # scale to ~±25k
        self.audio_to_short = blocks.float_to_short(1, 1)
        self.audio_udp = network.udp_sink(
            gr.sizeof_short, 1, "127.0.0.1", 42002, 0, 1472, True
        )

        # FFT spectrum path: probe raw IQ, compute FFT in Python thread
        fft_size = 256
        self.fft_s2v = blocks.stream_to_vector(gr.sizeof_gr_complex, fft_size)
        self.fft_probe = blocks.probe_signal_vc(fft_size)

        # Connect initial flowgraph (TETRA mode)
        self._connect_tetra()
        self.connect(self.src, self.fft_s2v, self.fft_probe)

    def _connect_tetra(self):
        """TETRA mode: LPF → phase demod → tetra-kit UDP + audio."""
        self.connect(self.src, self.lpf, self.demod_tetra, self.udp_sink)
        self.connect(self.demod_tetra, self.audio_resamp, self.audio_gain,
                     self.audio_to_short, self.audio_udp)

    def _connect_fm(self):
        """Analog FM mode: LPF → FM demod → audio only (no tetra-kit)."""
        self.connect(self.src, self.lpf, self.demod_fm)
        self.connect(self.demod_fm, self.audio_resamp, self.audio_gain,
                     self.audio_to_short, self.audio_udp)
        self.connect(self.demod_fm, self.null_float)  # keep tetra-kit path quiet

    def _connect_am(self):
        """Analog AM mode: LPF → mag → audio only."""
        self.connect(self.src, self.lpf, self.demod_am_mag, self.demod_am_dc)
        self.connect(self.demod_am_dc, self.audio_resamp, self.audio_gain,
                     self.audio_to_short, self.audio_udp)
        self.connect(self.demod_am_dc, self.null_float)

    def _connect_digital(self, demod_block):
        """Generic digital 4FSK mode: LPF → quad demod → audio (no tetra-kit)."""
        self.connect(self.src, self.lpf, demod_block)
        self.connect(demod_block, self.audio_resamp, self.audio_gain,
                     self.audio_to_short, self.audio_udp)
        self.connect(demod_block, self.null_float)

    def set_freq(self, freq):
        self.freq = float(freq)
        self.src.set_center_freq(self.freq, 0)
        return self.freq

    def get_freq(self):
        return self.freq

    def set_gain(self, gain):
        self.gain = float(gain)
        self.src.set_gain(self.gain, 0)
        return self.gain

    def get_gain(self):
        return self.gain

    def set_ppm(self, ppm):
        self.ppm = float(ppm)
        self.src.set_freq_corr(self.ppm, 0)
        return self.ppm

    def get_ppm(self):
        return self.ppm

    def set_mode(self, mode):
        mode = str(mode).lower()
        if mode not in MODES:
            return self.mode
        if mode == self.mode:
            return self.mode
        self.lock()
        try:
            self.disconnect_all()
            # FFT path is always connected
            self.connect(self.src, self.fft_s2v, self.fft_probe)
            if mode == 'tetra':
                self._connect_tetra()
            elif mode == 'dmr':
                self._connect_digital(self.demod_dmr)
            elif mode == 'p25':
                self._connect_digital(self.demod_p25)
            elif mode == 'nxdn':
                self._connect_digital(self.demod_nxdn)
            elif mode == 'dpmr':
                self._connect_digital(self.demod_dpmr)
            elif mode == 'analog_fm':
                self._connect_fm()
            elif mode == 'analog_am':
                self._connect_am()
            self.mode = mode
        finally:
            self.unlock()
        return self.mode

    def get_mode(self):
        return self.mode

    def get_signal_level(self):
        """Return current peak signal power (dB) in center 20% of FFT spectrum."""
        try:
            iq = self.fft_probe.level()
            if len(iq) != 256:
                return -120.0
            samples = np.array(iq, dtype=np.complex64)
            windowed = samples * np.hamming(256).astype(np.float32)
            spectrum = np.fft.fft(windowed)
            power = np.abs(spectrum) ** 2
            power = np.maximum(power, 1e-20)
            db = 10.0 * np.log10(power) - 80.0
            center_start = int(256 * 0.4)
            center_end = int(256 * 0.6)
            return float(np.max(db[center_start:center_end]))
        except Exception:
            return -120.0


def main():
    parser = argparse.ArgumentParser(description="TETRA Headless SDR Receiver")
    parser.add_argument("--freq", "-f", type=float, required=True, help="Center frequency in Hz (e.g. 390.525e6)")
    parser.add_argument("--gain", "-g", type=float, default=40, help="RF gain in dB (default: 40)")
    parser.add_argument("--ppm", "-p", type=float, default=0, help="Frequency correction in PPM")
    parser.add_argument("--samp-rate", "-s", type=float, default=2e6, help="Sample rate (default: 2M)")
    parser.add_argument("--rpc-port", type=int, default=42001, help="XML-RPC control port (default: 42001)")
    args = parser.parse_args()

    print(f"Starting TETRA receiver: freq={args.freq/1e6:.4f} MHz, gain={args.gain} dB, ppm={args.ppm}")

    tb = TetraReceiver(args.freq, args.gain, args.ppm, args.samp_rate)

    def sig_handler(sig, frame):
        print("\nStopping receiver...")
        tb.stop()
        tb.wait()
        sys.exit(0)

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    tb.start()

    # Start FFT computation thread: probes IQ, computes FFT, sends via UDP
    def fft_thread():
        fft_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        fft_size = 256
        fft_window = np.hamming(fft_size).astype(np.float32)
        avg_spectrum = None
        alpha = 0.3
        while True:
            try:
                import time
                time.sleep(1.0 / 15)  # ~15 fps
                iq = tb.fft_probe.level()
                if len(iq) != fft_size:
                    continue
                samples = np.array(iq, dtype=np.complex64)
                windowed = samples * fft_window
                spectrum = np.fft.fft(windowed)
                power = np.abs(spectrum) ** 2
                power = np.maximum(power, 1e-20)  # avoid log(0)
                db = (10.0 * np.log10(power) - 80.0).astype(np.float32)
                if avg_spectrum is None:
                    avg_spectrum = db.copy()
                else:
                    avg_spectrum = avg_spectrum * (1 - alpha) + db * alpha
                fft_sock.sendto(avg_spectrum.tobytes(), ("127.0.0.1", 42003))
            except Exception:
                pass
    threading.Thread(target=fft_thread, daemon=True).start()

    # Start XML-RPC control server for runtime tuning
    rpc = SimpleXMLRPCServer(("127.0.0.1", args.rpc_port), logRequests=False, allow_none=True)
    rpc.register_function(tb.get_freq, "get_freq")
    rpc.register_function(tb.set_freq, "set_freq")
    rpc.register_function(tb.get_gain, "get_gain")
    rpc.register_function(tb.set_gain, "set_gain")
    rpc.register_function(tb.get_ppm, "get_ppm")
    rpc.register_function(tb.set_ppm, "set_ppm")
    rpc.register_function(tb.get_mode, "get_mode")
    rpc.register_function(tb.set_mode, "set_mode")
    rpc.register_function(tb.get_signal_level, "get_signal_level")
    threading.Thread(target=rpc.serve_forever, daemon=True).start()
    print(f"XML-RPC control on 127.0.0.1:{args.rpc_port}")

    print("Receiver running. Sending symbols to UDP 127.0.0.1:42000")
    tb.wait()


if __name__ == "__main__":
    main()
