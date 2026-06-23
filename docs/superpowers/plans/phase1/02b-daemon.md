# WinSuperWhisper Phase 1 - Whisper Daemon (Python/WSL) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the WSL-side Python whisper daemon (`wsl/whisper_daemon.py`) test-first: the length-prefixed TCP frame protocol, the stdlib-`wave` WAV-to-float32 decoder, the injectable faster-whisper transcribe seam, and the single-connection serve loop with `READY` handshake plus `[EXIT]`/connection-drop shutdown.

**Architecture:** A standalone Python module exposing four testable seams - `send_frame`/`recv_frame` (wire framing), `wav_bytes_to_float32` (stdlib `wave` decode), `load_model`/`transcribe_pcm` (faster-whisper seam with lazy import), and `serve` (one persistent TCP connection). Tests inject a duck-typed **fake model**, so no whisper weights are ever downloaded and the whole suite runs offline in a Podman container with only `numpy` as a heavy import. `faster-whisper` is imported lazily inside `load_model`, never at module top level, so the tests never require it to be installed.

**Tech Stack:** Python 3.10+, stdlib `socket`/`struct`/`wave`/`argparse`/`threading`, numpy (only heavy dep imported in tests), faster-whisper (lazily imported, never imported by tests), pytest. Container test runner: Podman (container-sandbox skill).

---

## Scope and tags

**This entire file is tagged `PODMAN`** - every task here is verifiable on Linux in a Podman container with `numpy` and `pytest` installed. No Windows machine is needed for any task in this file.

This file builds **only** the Python whisper daemon piece of Phase 1. It depends on `01-foundation` (the standalone `WinSuperWhisper` repo, its `wsl/` directory, and `scripts/run-tests.sh` skeleton must already exist) and runs **in parallel with `02a-core`** (the C# Core piece); the two share no code.

The full design spec is authoritative for behavior and lives at the absolute path:
`/home/luna/projects/firstmate/docs/superpowers/specs/2026-06-22-winsuperwhisper-design.md`

The wire-format / names contract this file follows verbatim is the Phase 1 shared contract; the daemon-relevant clauses are quoted inline in each task. **Do not redesign any name, signature, constant, or byte sequence.**

---

## Binary exit conditions and escalation contract (read first)

**Exit conditions are binary.** Every task ends with a real `pytest` run that must be green. A red tree is never committed. The file-level "Exit conditions" checklist at the bottom must be fully green before this piece is considered done.

**Mechanical failures get a bounded 2-attempt retry.** A flaky import, a transient port bind, a typo in a path - fix and retry, at most twice. If it still fails after two attempts, stop and escalate with the exact command and output.

**Any judgment call stops and escalates immediately - do not improvise.** In particular:

- **Model-engine judgment call (escalate, do not swap engines):** the tests in this file use a **fake model** and must never touch real weights. If, while wiring `install.sh` or any environment setup, `faster-whisper` cannot import or load in the container, demands a GPU/CUDA, or otherwise refuses to run, **STOP and escalate**. Model strategy (which engine, CPU vs GPU, which weights) is the captain's call. Do **not** silently substitute `openai-whisper`, `whisper.cpp`, or any other engine, and do **not** weaken or skip a test to make it pass.
- Any ambiguous spec detail, any needed credential, or any temptation to weaken a test (loosen an assertion, add a `skip`, catch-and-ignore an error the test should see) stops and escalates instead.

**The fake-model contract (why tests stay offline):** `load_model(model_dir)` lazily imports `faster_whisper` _inside the function body_. `transcribe_pcm(model, audio_f32, language)` only calls `model.transcribe(...)` on a duck-typed object. Every test constructs its own fake object with a `.transcribe()` method, so `faster_whisper` is never imported during the test run and no weights are downloaded. The only heavy dependency actually imported by the tests is `numpy`.

---

## File structure

All paths are relative to the standalone `WinSuperWhisper` repo root.

- `wsl/whisper_daemon.py` - the daemon module. Grows across tasks: frame protocol (Task 2), WAV decode (Task 3), transcribe seam (Task 4), serve loop + argparse main (Task 5). One clear responsibility: be the transcription server, with each concern in its own function so tests drive it directly.
- `wsl/requirements.txt` - exactly two lines: `faster-whisper` and `numpy`. Nothing else.
- `wsl/install.sh` - creates a venv and `pip install`s `requirements.txt`. Not unit-tested (it provisions the real environment); validated by being shellcheck-clean and by a dry structural assertion in Task 1.
- `wsl/tests/test_protocol.py` - framing round-trip, partial-read reassembly, `READY`/`[EXIT]` constants, and the serve-loop handshake/exit/drop tests (these exercise the wire protocol end to end with a fake model).
- `wsl/tests/test_daemon.py` - WAV-to-float32 decoding (stdlib `wave` fixtures) and the transcribe seam (fake model).

The `wsl/` directory and the repo itself are created by `01-foundation`; this plan adds the files above.

---

## Podman test workflow (PODMAN)

All `pytest` commands below run inside a Podman container so the heavy `numpy` dependency is isolated from the host. Use the **container-sandbox** skill's workflow. The canonical one-shot pattern, runnable from the repo root:

```bash
# Run the daemon test suite in an isolated Podman container.
# Only numpy + pytest are installed; faster-whisper is NOT needed because
# every test injects a fake model (no weights downloaded, fully offline).
podman run --rm \
  -v "$PWD":/work:Z \
  -w /work \
  python:3.11-slim \
  bash -lc "pip install --quiet --root-user-action=ignore numpy pytest && pytest wsl/tests -v"
```

To run a single test (the form used in each task's run steps), swap the final `pytest` invocation, for example:

```bash
podman run --rm -v "$PWD":/work:Z -w /work python:3.11-slim \
  bash -lc "pip install --quiet --root-user-action=ignore numpy pytest && pytest wsl/tests/test_protocol.py::test_send_recv_frame_roundtrip -v"
```

Notes:

- `faster-whisper` is deliberately **not** installed in the test container. It is imported lazily inside `load_model`, which the tests never call, so the suite stays offline and fast. If a test ever fails with `ModuleNotFoundError: faster_whisper`, that is a bug in the test (it touched the real loader) - fix the test, do not install the heavy dep.
- The `:Z` SELinux relabel flag is harmless on non-SELinux hosts; keep it for portability.
- Per-task "Run" steps below show the bare `pytest wsl/tests/...::test_name -v` command for clarity; execute each inside the Podman wrapper above.

---

## Task 1: Project files - requirements, install script, test package

**Files:**

- Create: `wsl/requirements.txt`
- Create: `wsl/install.sh`
- Create: `wsl/tests/__init__.py`
- Test: `wsl/tests/test_protocol.py` (created here with a structural sanity test)

- [ ] **Step 1: Write the failing test**

Create `wsl/tests/test_protocol.py` with an initial structural test that pins the dependency contract (exactly `faster-whisper` and `numpy`) and confirms the install script exists and is executable.

```python
import os
import stat

HERE = os.path.dirname(__file__)
WSL_DIR = os.path.abspath(os.path.join(HERE, ".."))


def test_requirements_are_exactly_faster_whisper_and_numpy():
    req_path = os.path.join(WSL_DIR, "requirements.txt")
    with open(req_path, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    # Compare on package names only (allow optional version pins).
    names = {ln.split("==")[0].split(">=")[0].split("~=")[0].strip().lower() for ln in lines}
    assert names == {"faster-whisper", "numpy"}, names


def test_install_script_exists_and_is_executable():
    install_path = os.path.join(WSL_DIR, "install.sh")
    assert os.path.isfile(install_path)
    mode = os.stat(install_path).st_mode
    assert mode & stat.S_IXUSR, "install.sh must be executable"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest wsl/tests/test_protocol.py -v`
Expected: FAIL - `FileNotFoundError` for `wsl/requirements.txt` (and `wsl/install.sh`), because those files do not exist yet.

- [ ] **Step 3: Write minimal implementation**

Create `wsl/requirements.txt`:

```text
faster-whisper
numpy
```

Create `wsl/tests/__init__.py` (empty file, makes `wsl/tests` an importable package):

```python

```

Create `wsl/install.sh`:

```bash
#!/usr/bin/env bash
# Provision the WinSuperWhisper whisper daemon environment in WSL.
# Creates a Python venv in wsl/.venv and installs requirements (faster-whisper, numpy).
# Usage: ./install.sh   (run from anywhere; resolves its own directory)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"

if [ ! -d "${VENV_DIR}" ]; then
  python3 -m venv "${VENV_DIR}"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
python3 -m pip install --upgrade pip
python3 -m pip install -r "${SCRIPT_DIR}/requirements.txt"

echo "WinSuperWhisper daemon environment ready at ${VENV_DIR}"
```

Then mark it executable:

```bash
chmod +x wsl/install.sh
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest wsl/tests/test_protocol.py -v`
Expected: PASS - both `test_requirements_are_exactly_faster_whisper_and_numpy` and `test_install_script_exists_and_is_executable` green.

- [ ] **Step 5: Commit**

```bash
git add wsl/requirements.txt wsl/install.sh wsl/tests/__init__.py wsl/tests/test_protocol.py
git commit -m "chore(daemon): add wsl requirements, install script, test package"
```

---

## Task 2: Frame protocol - send_frame / recv_frame and the READY / EXIT constants

Contract (verbatim): every message is a frame `[4-byte little-endian uint32 length N][N payload bytes]`. `READY` control frame payload is exactly the 5 ASCII bytes `READY`. `EXIT` control frame payload is exactly the 6 ASCII bytes `[EXIT]`. `recv_frame` must reassemble across partial reads.

**Files:**

- Create: `wsl/whisper_daemon.py`
- Test: `wsl/tests/test_protocol.py:append`

- [ ] **Step 1: Write the failing test**

Append to `wsl/tests/test_protocol.py`:

```python
import socket

from wsl.whisper_daemon import send_frame, recv_frame, READY, EXIT


def test_constants_are_exact_ascii_bytes():
    assert READY == b"READY"
    assert EXIT == b"[EXIT]"
    assert isinstance(READY, bytes)
    assert isinstance(EXIT, bytes)


def test_send_recv_frame_roundtrip():
    a, b = socket.socketpair()
    try:
        payload = b"hello frame \x00\x01\x02 world"
        send_frame(a, payload)
        got = recv_frame(b)
        assert got == payload
    finally:
        a.close()
        b.close()


def test_send_frame_writes_little_endian_length_prefix():
    import struct
    a, b = socket.socketpair()
    try:
        payload = b"abcd"  # length 4
        send_frame(a, payload)
        # Read the raw 4-byte prefix off the wire, then the body.
        prefix = b.recv(4)
        assert prefix == struct.pack("<I", 4)
        body = b.recv(4)
        assert body == payload
    finally:
        a.close()
        b.close()


def test_recv_frame_reassembles_partial_reads():
    """recv_frame must loop until all N payload bytes arrive, even when the
    sender dribbles bytes out in several chunks (TCP gives no message boundary)."""
    import struct
    import threading

    a, b = socket.socketpair()
    payload = bytes(range(256)) * 40  # 10240 bytes, far above one MTU

    def dribble():
        framed = struct.pack("<I", len(payload)) + payload
        for i in range(0, len(framed), 7):  # tiny 7-byte chunks
            a.sendall(framed[i:i + 7])

    try:
        t = threading.Thread(target=dribble)
        t.start()
        got = recv_frame(b)
        t.join()
        assert got == payload
        assert len(got) == 10240
    finally:
        a.close()
        b.close()


def test_recv_frame_returns_none_on_clean_eof():
    """If the peer closes before sending any bytes, recv_frame signals EOF
    (returns None) so the serve loop can shut down instead of hanging."""
    a, b = socket.socketpair()
    try:
        a.close()  # peer gone, no frame sent
        got = recv_frame(b)
        assert got is None
    finally:
        b.close()


def test_recv_frame_returns_none_on_eof_mid_length_prefix():
    """A truncated length prefix (peer died mid-send) is treated as EOF, not a crash."""
    a, b = socket.socketpair()
    try:
        a.sendall(b"\x02\x00")  # only 2 of the 4 length bytes
        a.close()
        got = recv_frame(b)
        assert got is None
    finally:
        b.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest wsl/tests/test_protocol.py::test_send_recv_frame_roundtrip -v`
Expected: FAIL - `ImportError: cannot import name 'send_frame' from 'wsl.whisper_daemon'` (the module does not yet define the protocol functions or constants).

- [ ] **Step 3: Write minimal implementation**

Create `wsl/whisper_daemon.py`:

```python
"""WinSuperWhisper whisper daemon (WSL/Python side).

Length-prefixed TCP server that holds a faster-whisper model resident and
transcribes WAV bytes to UTF-8 text. See the design spec:
/home/luna/projects/firstmate/docs/superpowers/specs/2026-06-22-winsuperwhisper-design.md

Wire format: every message is a frame [4-byte little-endian uint32 length][payload].
  READY  control frame (daemon -> client): payload == b"READY"
  EXIT   control frame (client -> daemon): payload == b"[EXIT]"
  request (client -> daemon): payload is a complete in-memory WAV (starts b"RIFF")
  response (daemon -> client): payload is the UTF-8 transcript (may be empty)
"""

import struct

# Control-frame payloads, exact bytes per the wire contract.
READY = b"READY"
EXIT = b"[EXIT]"

_LEN_PREFIX = struct.Struct("<I")  # 4-byte little-endian unsigned length


def send_frame(sock, payload: bytes) -> None:
    """Send one length-prefixed frame: [4-byte LE uint32 length][payload]."""
    sock.sendall(_LEN_PREFIX.pack(len(payload)) + payload)


def _recv_exactly(sock, n: int):
    """Read exactly n bytes from sock, looping over partial reads.

    Returns the n bytes, or None if the peer closed before n bytes arrived (EOF).
    """
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:  # peer closed: clean or mid-stream EOF
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def recv_frame(sock):
    """Receive one length-prefixed frame, reassembling across partial reads.

    Returns the payload bytes, or None on EOF / connection drop (so the serve
    loop can shut down cleanly instead of hanging).
    """
    header = _recv_exactly(sock, _LEN_PREFIX.size)
    if header is None:
        return None
    (length,) = _LEN_PREFIX.unpack(header)
    if length == 0:
        return b""
    return _recv_exactly(sock, length)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest wsl/tests/test_protocol.py -v`
Expected: PASS - all framing tests green: constants exact, round-trip, little-endian prefix, partial-read reassembly, and both EOF cases return `None`.

- [ ] **Step 5: Commit**

```bash
git add wsl/whisper_daemon.py wsl/tests/test_protocol.py
git commit -m "feat(daemon): length-prefixed frame protocol with READY/EXIT constants"
```

---

## Task 3: WAV bytes -> float32 numpy array via stdlib wave

Contract (verbatim): incoming WAV is parsed with the stdlib `wave` module into a numpy float32 array normalized to [-1, 1] (16-bit PCM -> `samples.astype(np.float32) / 32768.0`). NO soundfile/scipy/ffmpeg. The C# app guarantees 16 kHz mono 16-bit; the daemon asserts that format and raises a clear error otherwise.

**Files:**

- Modify: `wsl/whisper_daemon.py` (add `wav_bytes_to_float32`)
- Test: `wsl/tests/test_daemon.py`

- [ ] **Step 1: Write the failing test**

Create `wsl/tests/test_daemon.py`:

```python
import io
import wave

import numpy as np
import pytest

from wsl.whisper_daemon import wav_bytes_to_float32


def _make_wav(samples_int16, sample_rate=16000, channels=1, sampwidth=2) -> bytes:
    """Build an in-memory WAV with the stdlib wave module (no third-party deps)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sampwidth)
        w.setframerate(sample_rate)
        w.writeframes(np.asarray(samples_int16, dtype="<i2").tobytes())
    return buf.getvalue()


def test_decodes_16k_mono_16bit_to_normalized_float32():
    samples = [0, 32767, -32768, 16384, -16384]
    wav = _make_wav(samples)
    out = wav_bytes_to_float32(wav)

    assert out.dtype == np.float32
    assert out.ndim == 1
    assert out.shape == (5,)
    # 16-bit PCM normalized by /32768.0
    expected = np.array(samples, dtype=np.float32) / 32768.0
    np.testing.assert_allclose(out, expected, rtol=0, atol=1e-7)
    # Values land in [-1, 1] (32767/32768 < 1; -32768/32768 == -1).
    assert out.max() <= 1.0
    assert out.min() >= -1.0


def test_payload_begins_with_riff_marker():
    """Sanity: our fixtures are real WAVs (the wire request starts with ASCII RIFF)."""
    wav = _make_wav([0, 1, 2])
    assert wav[:4] == b"RIFF"


def test_rejects_non_16k_sample_rate():
    wav = _make_wav([0, 1, 2], sample_rate=44100)
    with pytest.raises(ValueError) as exc:
        wav_bytes_to_float32(wav)
    assert "16000" in str(exc.value) or "16 kHz" in str(exc.value) or "16kHz" in str(exc.value)


def test_rejects_stereo():
    wav = _make_wav([0, 1, 2, 3], channels=2)
    with pytest.raises(ValueError) as exc:
        wav_bytes_to_float32(wav)
    assert "mono" in str(exc.value).lower() or "channel" in str(exc.value).lower()


def test_rejects_non_16bit_sample_width():
    # 8-bit PCM
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(16000)
        w.writeframes(bytes([128, 200, 60]))
    with pytest.raises(ValueError) as exc:
        wav_bytes_to_float32(buf.getvalue())
    assert "16-bit" in str(exc.value) or "16 bit" in str(exc.value) or "sample width" in str(exc.value).lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest wsl/tests/test_daemon.py::test_decodes_16k_mono_16bit_to_normalized_float32 -v`
Expected: FAIL - `ImportError: cannot import name 'wav_bytes_to_float32' from 'wsl.whisper_daemon'`.

- [ ] **Step 3: Write minimal implementation**

Add to `wsl/whisper_daemon.py`. First add the imports at the top of the file, just below the existing `import struct`:

```python
import io
import wave

import numpy as np
```

Then add the function (place it after `recv_frame`):

```python
def wav_bytes_to_float32(wav: bytes) -> np.ndarray:
    """Decode in-memory 16 kHz mono 16-bit PCM WAV bytes to a normalized float32 array.

    Uses only the Python stdlib `wave` module - no soundfile/scipy/ffmpeg.
    Returns a 1-D float32 numpy array in [-1, 1] (16-bit PCM divided by 32768.0).

    Raises ValueError with a clear message if the WAV is not 16 kHz, mono, or 16-bit,
    since the C# capture side is contracted to produce exactly that format.
    """
    with wave.open(io.BytesIO(wav), "rb") as w:
        channels = w.getnchannels()
        sampwidth = w.getsampwidth()
        framerate = w.getframerate()
        frames = w.readframes(w.getnframes())

    if framerate != 16000:
        raise ValueError(f"expected 16000 Hz (16 kHz) audio, got {framerate} Hz")
    if channels != 1:
        raise ValueError(f"expected mono audio (1 channel), got {channels} channels")
    if sampwidth != 2:
        raise ValueError(f"expected 16-bit PCM (sample width 2 bytes), got {sampwidth} bytes")

    samples = np.frombuffer(frames, dtype="<i2")
    return samples.astype(np.float32) / 32768.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest wsl/tests/test_daemon.py -v`
Expected: PASS - decode-to-normalized-float32, RIFF marker, and all three rejection tests (non-16k, stereo, non-16bit) green.

- [ ] **Step 5: Commit**

```bash
git add wsl/whisper_daemon.py wsl/tests/test_daemon.py
git commit -m "feat(daemon): decode 16k mono 16-bit WAV to float32 via stdlib wave"
```

---

## Task 4: Transcribe seam - load_model and transcribe_pcm (fake model in tests)

Contract (verbatim): faster-whisper model argument is a DIRECTORY (CTranslate2), created by `load_model(model_dir) -> model`; the transcription call goes through `transcribe_pcm(model, audio_f32, language) -> str` so tests inject a fake model and never download weights. faster-whisper is imported lazily inside `load_model`.

**Files:**

- Modify: `wsl/whisper_daemon.py` (add `load_model`, `transcribe_pcm`)
- Test: `wsl/tests/test_daemon.py:append`

- [ ] **Step 1: Write the failing test**

Append to `wsl/tests/test_daemon.py`:

```python
from wsl.whisper_daemon import transcribe_pcm


class _FakeSegment:
    """Duck-typed stand-in for a faster-whisper segment (has a .text attribute)."""
    def __init__(self, text):
        self.text = text


class _FakeModel:
    """Duck-typed stand-in for a faster-whisper WhisperModel.

    Records the call so the test can assert how transcribe_pcm invoked it,
    and returns (segments, info) like the real API - so no weights are needed.
    """
    def __init__(self, segments):
        self._segments = segments
        self.calls = []

    def transcribe(self, audio, language=None, **kwargs):
        self.calls.append({"audio": audio, "language": language, "kwargs": kwargs})
        info = object()  # faster-whisper returns (segments, info); info is unused here
        return iter(self._segments), info


def test_transcribe_pcm_joins_segment_texts():
    model = _FakeModel([_FakeSegment(" Hello"), _FakeSegment(" world.")])
    audio = np.zeros(16000, dtype=np.float32)
    result = transcribe_pcm(model, audio, "en")
    # Segment texts joined and stripped of surrounding whitespace.
    assert result == "Hello world."


def test_transcribe_pcm_passes_audio_and_language_to_model():
    model = _FakeModel([_FakeSegment("x")])
    audio = np.linspace(-0.5, 0.5, 100, dtype=np.float32)
    transcribe_pcm(model, audio, "es")
    assert len(model.calls) == 1
    call = model.calls[0]
    np.testing.assert_array_equal(call["audio"], audio)
    assert call["language"] == "es"


def test_transcribe_pcm_auto_language_passes_none():
    """language='auto' must become None so faster-whisper auto-detects."""
    model = _FakeModel([_FakeSegment("x")])
    transcribe_pcm(model, np.zeros(10, dtype=np.float32), "auto")
    assert model.calls[0]["language"] is None


def test_transcribe_pcm_empty_segments_returns_empty_string():
    model = _FakeModel([])
    result = transcribe_pcm(model, np.zeros(10, dtype=np.float32), "en")
    assert result == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest wsl/tests/test_daemon.py::test_transcribe_pcm_joins_segment_texts -v`
Expected: FAIL - `ImportError: cannot import name 'transcribe_pcm' from 'wsl.whisper_daemon'`.

- [ ] **Step 3: Write minimal implementation**

Add to `wsl/whisper_daemon.py` (after `wav_bytes_to_float32`):

```python
def load_model(model_dir: str):
    """Load a faster-whisper model from a CTranslate2 model DIRECTORY.

    faster-whisper is imported lazily here, NOT at module top level, so the unit
    tests (which inject a fake model and never call this) can run offline without
    faster-whisper installed and without downloading any weights.
    """
    from faster_whisper import WhisperModel  # lazy: heavy dep, only on real startup

    return WhisperModel(model_dir)


def transcribe_pcm(model, audio_f32, language) -> str:
    """Transcribe a float32 audio array through a (real or fake) whisper model.

    `model` is any object exposing a faster-whisper-style `transcribe(audio, language=...)`
    that yields segments with a `.text` attribute and returns (segments, info).
    `language` of "auto" (or empty) becomes None so the model auto-detects.
    Returns the concatenated, stripped transcript text (may be empty).
    """
    lang = None if (language is None or language == "auto" or language == "") else language
    segments, _info = model.transcribe(audio_f32, language=lang)
    text = "".join(segment.text for segment in segments)
    return text.strip()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest wsl/tests/test_daemon.py -v`
Expected: PASS - all transcribe-seam tests green (join, audio/language pass-through, `auto` -> `None`, empty segments -> `""`), and the earlier WAV tests still green. No `faster_whisper` import occurs because no test calls `load_model`.

- [ ] **Step 5: Commit**

```bash
git add wsl/whisper_daemon.py wsl/tests/test_daemon.py
git commit -m "feat(daemon): injectable transcribe seam with lazy faster-whisper import"
```

---

## Task 5: Serve loop - READY handshake, transcribe, [EXIT] and connection-drop shutdown, argparse main

Contract (verbatim): daemon binds `0.0.0.0:8765`, accepts ONE persistent connection, sends a `READY` frame after the model is loaded, then loops `recv_frame`; `[EXIT]` payload -> close and exit the serve loop; a WAV payload -> decode -> transcribe -> send UTF-8 transcript frame; connection drop (EOF) without `[EXIT]` -> also exit (no zombie). Request/response are strictly 1:1 and ordered on the single connection. Launch form: `python3 whisper_daemon.py --model <linux-model-dir> --host 0.0.0.0 --port 8765 [--language auto]`.

`serve` is written injectable: it takes an already-loaded `model` plus `host`/`port`, binds an ephemeral port when `port=0`, and accepts a callback so a test can learn the bound port and drive a real client socket on `127.0.0.1` from a thread.

**Files:**

- Modify: `wsl/whisper_daemon.py` (add `serve`, `main`, `__main__` guard)
- Test: `wsl/tests/test_protocol.py:append`

- [ ] **Step 1: Write the failing test**

Append to `wsl/tests/test_protocol.py`:

```python
import io
import threading
import wave

import numpy as np

from wsl.whisper_daemon import serve


class _FakeSegment:
    def __init__(self, text):
        self.text = text


class _FakeModel:
    """Fake whisper model: every transcribe call returns one fixed segment.
    Lets the serve-loop tests assert a deterministic transcript with no weights."""
    def __init__(self, text):
        self._text = text

    def transcribe(self, audio, language=None, **kwargs):
        return iter([_FakeSegment(self._text)]), object()


def _make_wav(samples_int16, sample_rate=16000, channels=1, sampwidth=2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sampwidth)
        w.setframerate(sample_rate)
        w.writeframes(np.asarray(samples_int16, dtype="<i2").tobytes())
    return buf.getvalue()


def _start_server(model, language="auto"):
    """Start serve() on an ephemeral 127.0.0.1 port in a background thread.

    Returns (thread, port). serve() reports its bound port via on_bound so the
    test can connect; port=0 asks the OS for a free port.
    """
    port_box = {}
    bound = threading.Event()

    def on_bound(p):
        port_box["port"] = p
        bound.set()

    def run():
        serve(host="127.0.0.1", port=0, model=model, language=language, on_bound=on_bound)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    assert bound.wait(timeout=5), "server never reported a bound port"
    return t, port_box["port"]


def test_serve_sends_ready_first_then_transcript_then_exit_stops_it():
    model = _FakeModel("the fake transcript")
    t, port = _start_server(model)

    client = socket.create_connection(("127.0.0.1", port), timeout=5)
    try:
        # READY arrives before any transcription is accepted.
        assert recv_frame(client) == READY

        # A WAV request returns the deterministic fake transcript as UTF-8.
        send_frame(client, _make_wav([0, 100, -100, 200]))
        resp = recv_frame(client)
        assert resp == b"the fake transcript"
        assert resp.decode("utf-8") == "the fake transcript"

        # A second request works too (persistent connection, 1:1 ordered).
        send_frame(client, _make_wav([1, 2, 3]))
        assert recv_frame(client) == b"the fake transcript"

        # [EXIT] stops the serve loop cleanly.
        send_frame(client, EXIT)
    finally:
        client.close()

    t.join(timeout=5)
    assert not t.is_alive(), "serve() did not exit after [EXIT]"


def test_serve_exits_on_client_disconnect_without_exit_frame():
    """Backstop: if the client vanishes without sending [EXIT], the daemon
    must self-terminate (no zombie) rather than hang on recv."""
    model = _FakeModel("unused")
    t, port = _start_server(model)

    client = socket.create_connection(("127.0.0.1", port), timeout=5)
    assert recv_frame(client) == READY
    # Drop the connection abruptly - no [EXIT].
    client.close()

    t.join(timeout=5)
    assert not t.is_alive(), "serve() did not exit after client disconnect"


def test_serve_returns_empty_transcript_frame_for_empty_segments():
    model = _FakeModel("")  # whisper produced nothing (silence)
    t, port = _start_server(model)

    client = socket.create_connection(("127.0.0.1", port), timeout=5)
    try:
        assert recv_frame(client) == READY
        send_frame(client, _make_wav([0, 0, 0]))
        # An empty transcript is still a valid 1:1 response frame (zero-length payload).
        assert recv_frame(client) == b""
        send_frame(client, EXIT)
    finally:
        client.close()
    t.join(timeout=5)
    assert not t.is_alive()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest wsl/tests/test_protocol.py::test_serve_sends_ready_first_then_transcript_then_exit_stops_it -v`
Expected: FAIL - `ImportError: cannot import name 'serve' from 'wsl.whisper_daemon'`.

- [ ] **Step 3: Write minimal implementation**

Add to `wsl/whisper_daemon.py`. First add `argparse` and `socket` to the imports near the top (below `import struct`):

```python
import argparse
import socket
```

Then add `serve`, `main`, and the `__main__` guard at the end of the file:

```python
def serve(host, port, model, language, on_bound=None) -> None:
    """Run the single-connection transcription server until [EXIT] or disconnect.

    Binds host:port (use port=0 for an ephemeral port - the contract daemon binds
    0.0.0.0:8765). Accepts ONE persistent connection, sends a READY frame after the
    model is ready, then loops:
      - recv_frame() == EXIT          -> break and exit cleanly
      - recv_frame() is None (EOF)    -> client gone, break and exit (no zombie)
      - any other payload (a WAV)     -> decode -> transcribe -> send UTF-8 transcript

    `model` is an already-loaded (real or fake) whisper model, making serve injectable.
    `on_bound`, if given, is called with the actual bound port once the listener is up
    (so a test driving an ephemeral port can connect).
    """
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind((host, port))
        listener.listen(1)
        if on_bound is not None:
            on_bound(listener.getsockname()[1])

        conn, _addr = listener.accept()
        try:
            # Handshake: model is loaded, signal readiness before accepting audio.
            send_frame(conn, READY)
            while True:
                payload = recv_frame(conn)
                if payload is None:
                    break  # connection dropped without [EXIT]; self-terminate
                if payload == EXIT:
                    break  # explicit clean shutdown
                audio = wav_bytes_to_float32(payload)
                transcript = transcribe_pcm(model, audio, language)
                send_frame(conn, transcript.encode("utf-8"))
        finally:
            conn.close()
    finally:
        listener.close()


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="WinSuperWhisper whisper daemon")
    parser.add_argument("--model", required=True,
                        help="path to the faster-whisper CTranslate2 model DIRECTORY")
    parser.add_argument("--host", default="0.0.0.0", help="bind host (default 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8765, help="bind port (default 8765)")
    parser.add_argument("--language", default="auto",
                        help="transcription language, or 'auto' to detect (default auto)")
    args = parser.parse_args(argv)

    model = load_model(args.model)
    serve(host=args.host, port=args.port, model=model, language=args.language)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest wsl/tests/test_protocol.py -v`
Expected: PASS - the full protocol file is green: framing/EOF tests plus the serve-loop tests (READY-first then deterministic fake transcript, persistent second request, `[EXIT]` stops it, client-disconnect stops it, empty-segments returns an empty frame).

- [ ] **Step 5: Commit**

```bash
git add wsl/whisper_daemon.py wsl/tests/test_protocol.py
git commit -m "feat(daemon): single-connection serve loop with READY handshake and EXIT/drop shutdown"
```

---

## Task 6: Full-suite green and run-tests.sh wiring confirmation

Confirm the whole daemon suite passes together in the Podman container and that the Tier-1 `pytest wsl/tests` invocation in `scripts/run-tests.sh` (created by `01-foundation`) actually exercises these tests.

**Files:**

- (No new files; verification + a guard test)
- Test: `wsl/tests/test_daemon.py:append`

- [ ] **Step 1: Write the failing test**

Append a guard test to `wsl/tests/test_daemon.py` that proves `faster_whisper` is never imported by the test run (the offline guarantee):

```python
import sys


def test_faster_whisper_is_not_imported_during_tests():
    """The whole point of the fake-model seam: importing the daemon module and
    running its unit tests must NOT pull in faster-whisper (heavy / needs weights).
    If this fails, a test wrongly called load_model() with a real backend."""
    import wsl.whisper_daemon  # noqa: F401  (ensure the module is imported)
    assert "faster_whisper" not in sys.modules
```

- [ ] **Step 2: Run test to verify it fails (or passes for the right reason)**

Run: `pytest wsl/tests/test_daemon.py::test_faster_whisper_is_not_imported_during_tests -v`
Expected: PASS immediately if `faster_whisper` is genuinely not installed/imported in the container (the lazy import holds). If it FAILS with `faster_whisper` present in `sys.modules`, that is a real regression - a test touched `load_model` with a real backend; STOP and fix the offending test, do not weaken this guard.

- [ ] **Step 3: Minimal implementation**

No production code change. The lazy import in `load_model` (Task 4) is what makes this guard green; this task only locks the guarantee in place.

- [ ] **Step 4: Run the full suite to verify everything is green**

Run the whole daemon suite in Podman (the canonical wrapper from the "Podman test workflow" section):

```bash
podman run --rm -v "$PWD":/work:Z -w /work python:3.11-slim \
  bash -lc "pip install --quiet --root-user-action=ignore numpy pytest && pytest wsl/tests -v"
```

Expected: PASS - every test in `wsl/tests/test_protocol.py` and `wsl/tests/test_daemon.py` green, zero skips, with only `numpy` (plus `pytest`) installed and **no** `faster-whisper`.

- [ ] **Step 5: Commit**

```bash
git add wsl/tests/test_daemon.py
git commit -m "test(daemon): guard that the test suite never imports faster-whisper"
```

---

## Self-review (spec coverage)

- **Frame protocol** (4-byte LE length prefix, `READY`=`b"READY"`, `EXIT`=`b"[EXIT]"`, partial-read reassembly): Task 2.
- **WAV -> float32 via stdlib `wave`, /32768.0 normalization, 16k/mono/16-bit assertions**: Task 3.
- **Transcribe seam** (`load_model` directory arg with lazy faster-whisper import; `transcribe_pcm` joins segments; fake-model injection): Task 4.
- **Serve loop** (binds host:port, single persistent connection, `READY` after load, WAV->transcript, `[EXIT]` break, EOF/drop break, argparse `--model/--host/--port/--language` with the contract defaults): Task 5.
- **requirements.txt = faster-whisper + numpy only; install.sh venv + pip**: Task 1.
- **Offline / no-weights guarantee**: Task 4 (lazy import) + Task 6 (guard test).

Names and bytes used verbatim from the contract: `send_frame`, `recv_frame`, `READY`, `EXIT`, `wav_bytes_to_float32`, `load_model`, `transcribe_pcm`, `serve`; `0.0.0.0`/`8765` defaults; `[4-byte little-endian uint32 length][payload]` framing.

---

## Exit conditions (all must be green)

This piece is done only when every box below is checked, all verified in Podman on Linux:

- [ ] `pytest wsl/tests/test_protocol.py -v` green: frame round-trip, little-endian length prefix, and partial-read reassembly all pass.
- [ ] `READY` handshake verified: the serve loop sends a `READY` frame first, before accepting any transcription.
- [ ] `[EXIT]` shutdown verified: an `[EXIT]` frame stops the serve loop and `serve()` returns (thread not alive).
- [ ] Connection-drop shutdown verified: a client disconnect without `[EXIT]` also stops the serve loop (no zombie, no hang).
- [ ] WAV -> numpy verified on a fixture: `wav_bytes_to_float32` decodes a known in-memory `wave`-built 16k mono 16-bit WAV to a normalized float32 array, and rejects non-16k / stereo / non-16-bit with clear errors.
- [ ] Deterministic round-trip verified: a known WAV sent over a real `127.0.0.1` client socket returns the exact fake-model transcript as a UTF-8 frame.
- [ ] Offline guarantee verified: the full `pytest wsl/tests -v` suite passes in the Podman container with only `numpy` + `pytest` installed and `faster-whisper` absent (`faster_whisper` never enters `sys.modules`).
- [ ] `requirements.txt` is exactly `faster-whisper` + `numpy`; `install.sh` is executable and creates a venv + pip-installs requirements.

**Dependencies:** this file depends on `01-foundation` (repo, `wsl/` directory, and `scripts/run-tests.sh` skeleton must exist) and runs **in parallel with `02a-core`** (no shared code).

**Escalation reminder:** if `faster-whisper` cannot import or load in the container, demands a GPU, or otherwise refuses - STOP and escalate (model strategy is the captain's call). Never swap engines or weaken a test to go green.
