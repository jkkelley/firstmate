# WinSuperWhisper - Design Spec

**Date:** 2026-06-22
**Status:** Approved

---

## Overview

WinSuperWhisper is a Windows 11 dictation app modeled on OpenSuperWhisper (macOS).
The user holds a global hotkey to record speech, releases to transcribe, and the text is automatically typed into whatever window is focused.
It runs as a C# WPF app on Windows with a persistent Python whisper daemon in WSL handling transcription.

---

## Architecture

### Components

**WinSuperWhisper.exe** (C# WPF, Windows)

Owns all Windows-side concerns:

- Global hotkey registration via Win32 `RegisterHotKey`
- Microphone capture via NAudio at 16kHz mono (whisper's required format)
- Recording overlay UI
- Text injection into the active window via Win32 `SendInput`
- Settings window and config persistence
- WSL daemon lifecycle management (start, monitor, restart)

**whisper-daemon** (Python, WSL)

Owns all transcription concerns:

- Loads and holds the faster-whisper model in memory.
  faster-whisper runs on the CTranslate2 engine, so a "model" is a directory (containing `model.bin`, `config.json`, `vocabulary.txt`, etc.), not a single file.
- TCP server bound to `0.0.0.0:8765`.
  Binding to `0.0.0.0` rather than `localhost` avoids a WSL2 gotcha where Windows may resolve `localhost` to IPv6 (`::1`) while a `localhost`-bound Python server only listens on IPv4 (`127.0.0.1`), producing "connection refused".
  The C# client always connects to `127.0.0.1`.
- Accepts WAV bytes, returns UTF-8 transcript text.
  faster-whisper's `transcribe()` wants a `float32` numpy array.
  Because the C# app controls the audio format (16kHz mono PCM from NAudio), the daemon parses the incoming WAV with the Python stdlib `wave` module into a numpy `float32` array - no `soundfile`/`scipy`/ffmpeg dependency needed.

### IPC Protocol

Both sides speak a simple length-prefixed binary protocol over a persistent TCP connection.

**Handshake (cold-start guard).**
The model takes several seconds to load into RAM.
On connect, before accepting any audio, the daemon sends a `READY` control frame once the model is fully loaded.
The C# app keeps the hotkey gated and the tray in a "warming up" state until `READY` arrives, so a hotkey press during model load cannot produce a failed or timed-out transcription.

**Transcription request/response.**

- C# sends: `[4-byte little-endian length][WAV file bytes]`
- Daemon responds: `[4-byte little-endian length][UTF-8 transcript]`

**Shutdown.**
On app exit the C# client sends an explicit `[EXIT]` control frame so the daemon terminates cleanly.
As a backstop against the app crashing without sending `[EXIT]`, the daemon also self-terminates when the persistent connection drops - this prevents zombie Python processes lingering in WSL.

The connection is persistent - the daemon stays up across transcriptions.
The C# client reconnects automatically on failure (and re-waits for `READY`).

### Key Design Principle

Every Windows-specific API is hidden behind an interface.
This allows the orchestrator and all business logic to be tested on Linux in Podman via mocks.
Only the thin Win32 adapter implementations require a real Windows environment to test.

**This is enforced by the project split, not just convention.**
The solution is strictly two projects:

- **`WinSuperWhisper.Core`** - a `net8.0` class library holding the interfaces, orchestrator, config models, the TCP/IPC protocol client, and WAV encoding.
  It references no WPF assemblies (`PresentationFramework`, `PresentationCore`, `WindowsBase`) and no Windows-only audio library, so it compiles and tests on Linux in Podman.
- **`WinSuperWhisper.App`** - a `net8.0-windows` WPF app holding the UI, the Win32 adapter implementations, and the NAudio microphone-capture implementation.
  NAudio is Windows-only, so the real `IAudioCapture` lives here, not in Core.

If any WPF type (e.g. `Dispatcher`) or NAudio type leaks into Core, the Podman build breaks immediately - that is the intended guardrail.

Interfaces (defined in Core):

- `IHotkeyService` - global hotkey register/unregister, press/release events
- `IAudioCapture` - start/stop mic capture, PCM sample stream
- `ITextInjector` - inject text into active window
- `IMonitorService` - enumerate monitors, get working area
- `IDaemonClient` - send WAV bytes, receive transcript

---

## UI Design

### Recording Overlay

Appears on hotkey press, dismissed after transcription completes.

- Borderless WPF window, `Topmost = true`, no taskbar entry
- Centered horizontally on the user-configured monitor
- Vertically positioned so the bottom edge sits 48 physical pixels (half inch at 96 DPI) above the taskbar - calculated dynamically from monitor working area using DPI-aware APIs (`GetDpiForMonitor`) so the gap scales correctly at 125%, 150%, and other scale factors
- Approximate size: 320 x 56px
- Left side: solid red square (~32x32px), pulses slightly while recording
- Right side: real-time bar graph waveform - ~20 vertical bars driven by mic sample amplitude, updates at 30fps
- On hotkey release: red square swaps to a spinner, bars freeze - "transcribing" state
- Dark background, slight rounded corners, subtle drop shadow

### Settings Window

Standard WPF window, accessible from system tray right-click menu.

**Display tab**

- Monitor list detected at launch (name + resolution)
- Radio selection for which monitor receives the overlay

**Hotkey tab**

- Key combo picker (Phase 1)
- Toggle mode switch (added Phase 3)

**Transcription tab**

- WSL distro selector
- Whisper model **folder** picker (faster-whisper/CTranslate2 models are directories, not single files) - uses the Windows UNC path `\\wsl$\<distro>\path\to\model-dir` so the standard Windows folder dialog can browse into the WSL filesystem; the selected path is stored in config and converted to a Linux path when passed to the daemon
- Language dropdown (auto-detect default)

**Output tab**

- Auto-type toggle (Phase 1)
- Clipboard copy toggle (Phase 2)

### System Tray Icon

- Right-click: opens Settings, shows last transcript, Exit
- Left-click: shows last transcript

### Config Persistence

Saved to `%APPDATA%\WinSuperWhisper\config.json`.

---

## Data Flow

### Startup

1. Load `config.json`
2. Launch WSL daemon: `wsl.exe -d <configured-distro> -e python <linux-path-to-whisper_daemon.py>` where the distro and script path come from config
3. Open persistent TCP connection to `127.0.0.1:8765`
4. Tray shows "warming up"; hotkey stays gated until the daemon sends `READY` (model fully loaded)
5. Register global hotkey with Win32 `RegisterHotKey`
6. On `READY`: tray switches to idle, hotkey armed

### Recording and Transcription

1. **Hotkey pressed**
   - Capture currently-focused window handle via `GetForegroundWindow`
   - Show recording overlay on configured monitor
   - Start NAudio mic capture at 16kHz mono
   - Feed amplitude samples to waveform bar graph at 30fps

2. **Hotkey released**
   - Stop mic capture
   - Overlay switches to "transcribing" state (spinner, frozen bars)
   - Encode captured PCM to WAV bytes in memory (no temp file)
   - Send over TCP: `[4-byte length][WAV bytes]`

3. **Daemon processes**
   - Receives WAV bytes
   - Passes to faster-whisper (model already in memory)
   - Sends back: `[4-byte length][UTF-8 transcript]`

4. **C# receives transcript**
   - Dismiss overlay
   - Restore focus to saved window handle via `SetForegroundWindow`
   - Inject text via `SendInput` keystroke simulation

### Failure Paths

- **Daemon not running:** auto-restart it, retry once, show brief error toast if second attempt fails
- **Transcription empty or silence detected:** dismiss overlay silently, no injection
- **SendInput fails / blocked by UIPI:** internal safety fallback - write transcript to clipboard and send Ctrl+V silently.
  This is distinct from the Phase 2 user-facing clipboard copy feature; it is a last-resort recovery path that exists in Phase 1.
  Note on **UIPI (User Interface Privilege Isolation):** when the focused window belongs to an elevated (Administrator) process - e.g. an elevated terminal or Task Manager - `SendInput` is silently blocked (returns 0) unless WinSuperWhisper is itself elevated.
  We deliberately do **not** auto-elevate (it is a security downgrade and breaks other interactions); instead we detect the `SendInput` 0-return and route through the clipboard fallback, and document the elevated-window limitation.
- **Focus drift:** the focused window handle is saved on hotkey press and restored on transcript arrival via `SetForegroundWindow`.
  Windows blocks background apps from stealing focus, so if the user clicked elsewhere while waiting, a plain `SetForegroundWindow` only flashes the taskbar.
  The restore therefore uses the `AttachThreadInput` trick to bypass the foreground lock; if restore still fails, the documented fallback behavior is to inject into whatever window currently has focus.
  This path can only be validated on a real Windows machine and is hardened in Phase 4.

---

## Project Structure

```
WinSuperWhisper/
  src/
    WinSuperWhisper.Core/           # net8.0 class library - NO WPF, NO NAudio
      Interfaces/                   # IHotkeyService, IAudioCapture,
                                    # ITextInjector, IMonitorService,
                                    # IDaemonClient
      Orchestrator/                 # Wires interfaces together (pure logic)
      Audio/                        # WAV encoding (PCM -> WAV bytes)
      Daemon/                       # TCP/IPC client: handshake, request, EXIT
      Models/
        AppConfig.cs
    WinSuperWhisper.App/            # net8.0-windows WPF app
      App.xaml
      Windows/
        OverlayWindow.xaml          # Recording overlay
        SettingsWindow.xaml
      Win32/                        # Real Win32 adapters (hotkey, SendInput,
                                    # monitor detection, AttachThreadInput)
      Audio/                        # NAudio mic-capture impl (Windows-only)
    WinSuperWhisper.Tests/          # xUnit - references Core only, runs in Podman
      Orchestrator/                 # Full pipeline via mocked interfaces
      Audio/                        # WAV encoding, PCM conversion
      Daemon/                       # TCP protocol, handshake, reconnect logic
    WinSuperWhisper.App.Tests/      # xUnit - Win32 adapters + UI smoke, Windows-only
  wsl/
    whisper_daemon.py               # Python TCP server
    requirements.txt
    install.sh
    tests/
      test_daemon.py                # Protocol, model loading, transcription
      test_protocol.py              # Wire format tests
  scripts/
    run-tests.sh                    # Full suite: Podman then powershell.exe
    win-tests.ps1                   # Windows-side dotnet test runner
    handoff-brief.sh                # Drops brief for Win11 Claude if needed
  docs/
    superpowers/specs/
      2026-06-22-winsuperwhisper-design.md
```

---

## Test Strategy

| Layer                                   | Test project    | Tool                                                                                                                | Runs in                               |
| --------------------------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------- | ------------------------------------- |
| WAV encoding, config, protocol          | `.Tests` (Core) | xUnit + mocks                                                                                                       | Podman                                |
| TCP daemon client (handshake, EXIT)     | `.Tests` (Core) | xUnit + mock TCP server                                                                                             | Podman                                |
| Orchestrator (full pipeline)            | `.Tests` (Core) | xUnit + all interfaces mocked                                                                                       | Podman                                |
| Python daemon                           | `wsl/tests`     | pytest                                                                                                              | Podman                                |
| Win32 adapters (hotkey, mic, SendInput) | `.App.Tests`    | xUnit, real Win32                                                                                                   | Windows via `powershell.exe` from WSL |
| UI smoke test                           | `.App.Tests`    | xUnit + `Application.Run` in a headless WPF test host; verifies overlay appears, positions correctly, and dismisses | Windows via `powershell.exe` from WSL |

`run-tests.sh` runs Podman tier then invokes `powershell.exe` for the Windows tier.
Exits non-zero if either fails.
No human in the loop for the test run.

---

## Build Phases

Every phase: tests written first, `run-tests.sh` green before moving to the next phase.
Each phase ships as its own PR.

### Phase 1 - Core MVP: hold-to-record + auto-type

- `WinSuperWhisper.Core` / `WinSuperWhisper.App` project split established
- WSL daemon: TCP server bound to `0.0.0.0:8765`, faster-whisper model loading, `READY` handshake, WAV-to-numpy via stdlib `wave`, transcription endpoint, `[EXIT]` + connection-drop shutdown
- All C# interfaces defined (in Core)
- All Win32 adapters: hotkey, mic capture (NAudio, in App), SendInput, monitor detection
- WAV encoding pipeline (PCM in, WAV bytes out)
- Daemon client: handshake gate, request/response, EXIT on shutdown, reconnect
- Recording overlay UI: red square + waveform bar graph (DPI-aware positioning)
- Orchestrator wiring all components together
- Settings: monitor selection + hotkey picker + WSL distro + model folder picker
- System tray icon ("warming up" / idle states) + settings window shell
- SendInput-0 detection → clipboard fallback (covers UIPI-blocked elevated windows)
- `run-tests.sh` automation script

### Phase 2 - Clipboard copy output

- Second `ITextInjector` implementation: write to clipboard + Ctrl+V
- Settings Output tab: auto-type toggle, clipboard copy toggle
- Tests for both output paths

### Phase 3 - Toggle trigger mode

- Toggle state machine added to hotkey service (press-to-start / press-to-stop)
- Settings Hotkey tab: toggle mode switch
- Tests for all state transitions

### Phase 4 - Polish

- Transcribing spinner animation
- Error toast on daemon failure with auto-restart
- Silence detection (skip injection on empty transcript)
- Focus-restore hardening: `AttachThreadInput` foreground-lock bypass, validated on real Windows
- Win11 Claude UI review pass

---

## Dependencies

**C# / Windows**

- .NET 8 (LTS) - `WinSuperWhisper.Core` (`net8.0`) + `WinSuperWhisper.App` (`net8.0-windows`)
- WPF (Windows Presentation Foundation) - App project only
- NAudio - microphone capture - App project only (Windows-only, cannot live in Core)
- xUnit - unit testing
- Moq - mocking in tests

**Python / WSL**

- Python 3.10+
- faster-whisper - transcription (CTranslate2 engine; model is a directory; stays resident in RAM)
- numpy - WAV bytes parsed via stdlib `wave` into a `float32` array (no `soundfile`/`scipy`/ffmpeg)
- pytest - daemon tests

**Tooling**

- Podman - container test runner
- `powershell.exe` - invoked from WSL for Windows-side test tier
