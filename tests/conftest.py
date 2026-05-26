"""Shared pytest fixtures.

The `tiny_mp3_path` fixture provides a small, deterministic, valid MP3 file
for integration tests. It is generated once via lameenc (pure-Python LAME
bindings, no ffmpeg/system dependency) and cached to tests/fixtures/.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
TINY_MP3 = FIXTURES_DIR / "tiny_silent_2s.mp3"


def _generate_tiny_mp3(out_path: Path) -> None:
    """Encode 2 seconds of silence as a 64 kbps mono MP3 (~16 KB)."""
    import lameenc

    sample_rate = 44100
    n_samples = sample_rate * 2  # 2 seconds
    # 16-bit signed little-endian PCM, all zeros.
    silent_pcm = struct.pack("<" + "h" * n_samples, *([0] * n_samples))

    encoder = lameenc.Encoder()
    encoder.set_bit_rate(64)
    encoder.set_in_sample_rate(sample_rate)
    encoder.set_channels(1)
    encoder.set_quality(2)
    mp3 = encoder.encode(silent_pcm) + encoder.flush()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(mp3)


@pytest.fixture(scope="session")
def tiny_mp3_path() -> Path:
    """Return the path to a small (~16 KB) valid silent MP3, generating it once."""
    if not TINY_MP3.exists():
        _generate_tiny_mp3(TINY_MP3)
    return TINY_MP3
