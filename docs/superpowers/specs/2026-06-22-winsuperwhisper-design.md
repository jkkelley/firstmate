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

- Loads and holds the faster-whisper model in memory
- TCP server on `localhost:8765` (WSL2 exposes localhost ports to Windows automatically)
- Accepts WAV bytes, returns UTF-8 transcript text

### IPC Protocol

Both sides speak a simple length-prefixed binary protocol over a persistent TCP connection.

- C# sends: `[4-byte little-endian length][WAV file bytes]`
- Daemon responds: `[4-byte little-endian length][UTF-8 transcript]`

The connection is persistent - the daemon stays up across transcriptions.
The C# client reconnects automatically on failure.

### Key Design Principle

Every Windows-specific API is hidden behind an interface.
This allows the orchestrator and all business logic to be tested on Linux in Podman via mocks.
Only the thin Win32 adapter implementations require a real Windows environment to test.

Interfaces:

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
- Whisper model file picker - uses the Windows UNC path `\\wsl$\<distro>\path\to\model.bin` so the standard Windows file dialog can browse into the WSL filesystem; the selected path is stored in config and converted to a Linux path when passed to the daemon
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
3. Open persistent TCP connection to `localhost:8765`
4. Register global hotkey with Win32 `RegisterHotKey`
5. Sit in system tray, idle

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
- **SendInput fails:** internal safety fallback - write transcript to clipboard and send Ctrl+V silently.
  This is distinct from the Phase 2 user-facing clipboard copy feature; it is a last-resort recovery path that exists in Phase 1.

---

## Project Structure

```
WinSuperWhisper/
  src/
    WinSuperWhisper/
      App.xaml
      Windows/
        OverlayWindow.xaml          # Recording overlay
        SettingsWindow.xaml
      Services/
        Interfaces/                 # IHotkeyService, IAudioCapture,
                                    # ITextInjector, IMonitorService,
                                    # IDaemonClient
        Win32/                      # Real Win32 adapter implementations
        Audio/                      # NAudio capture + WAV encoding
        Daemon/                     # TCP client to WSL daemon
      Models/
        AppConfig.cs
    WinSuperWhisper.Tests/          # xUnit - runs on Linux in Podman
      Services/                     # Tests via mocks against interfaces
      Audio/                        # WAV encoding, PCM conversion
      Daemon/                       # TCP protocol, reconnect logic
      Integration/                  # Full pipeline with mock daemon
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

| Layer                                   | Tool                                                                                                                | Runs in                               |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------- | ------------------------------------- |
| WAV encoding, config, protocol          | xUnit + mocks                                                                                                       | Podman                                |
| TCP daemon client                       | xUnit + mock TCP server                                                                                             | Podman                                |
| Orchestrator (full pipeline)            | xUnit + all interfaces mocked                                                                                       | Podman                                |
| Python daemon                           | pytest                                                                                                              | Podman                                |
| Win32 adapters (hotkey, mic, SendInput) | xUnit, real Win32                                                                                                   | Windows via `powershell.exe` from WSL |
| UI smoke test                           | xUnit + `Application.Run` in a headless WPF test host; verifies overlay appears, positions correctly, and dismisses | Windows via `powershell.exe` from WSL |

`run-tests.sh` runs Podman tier then invokes `powershell.exe` for the Windows tier.
Exits non-zero if either fails.
No human in the loop for the test run.

---

## Build Phases

Every phase: tests written first, `run-tests.sh` green before moving to the next phase.
Each phase ships as its own PR.

### Phase 1 - Core MVP: hold-to-record + auto-type

- WSL daemon: TCP server, faster-whisper model loading, transcription endpoint
- All C# interfaces defined
- All Win32 adapters: hotkey, mic capture, SendInput, monitor detection
- WAV encoding pipeline (PCM in, WAV bytes out)
- Recording overlay UI: red square + waveform bar graph
- Orchestrator wiring all components together
- Settings: monitor selection + hotkey picker
- System tray icon + settings window shell
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
- Win11 Claude UI review pass

---

## Dependencies

**C# / Windows**

- .NET 8 (LTS)
- WPF (Windows Presentation Foundation)
- NAudio - microphone capture
- xUnit - unit testing
- Moq - mocking in tests

**Python / WSL**

- Python 3.10+
- faster-whisper - transcription (faster than raw whisper.cpp, pure Python, model stays resident)
- pytest - daemon tests

**Tooling**

- Podman - container test runner
- `powershell.exe` - invoked from WSL for Windows-side test tier
