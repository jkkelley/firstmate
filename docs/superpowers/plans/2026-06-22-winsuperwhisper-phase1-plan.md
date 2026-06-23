# WinSuperWhisper - Phase 1 Implementation Plan (Core MVP: hold-to-record + auto-type)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> This is the **overview / index**. The actual task-by-task plans live in [`phase1/`](./phase1/) - one file per build piece. Build them in the order below.

**Goal:** Ship the Phase 1 Core MVP of WinSuperWhisper - hold a global hotkey to record speech, release to transcribe via a persistent Python whisper daemon in WSL, and auto-type the transcript into the focused window.

**Architecture:** A standalone repo with a strict two-project split. `WinSuperWhisper.Core` (`net8.0`, no WPF, no NAudio) holds all interfaces, models, the orchestrator, WAV encoding, and the TCP/IPC client - so it compiles and tests on Linux in Podman. `WinSuperWhisper.App` (`net8.0-windows`) holds the WPF UI, the Win32 adapters, and NAudio mic capture. A persistent Python daemon in WSL loads a faster-whisper model and serves transcriptions over a length-prefixed TCP protocol. The compiler enforces the test boundary: any WPF/NAudio leak into Core breaks the Linux build.

**Tech Stack:** .NET 8 (C#, WPF, Win32 P/Invoke, NAudio), Python 3.10+ (faster-whisper, numpy), xUnit + Moq, pytest, Podman (Linux test tier), `powershell.exe` from WSL (Windows test tier).

**Spec (authoritative for behavior):** `/home/luna/projects/firstmate/docs/superpowers/specs/2026-06-22-winsuperwhisper-design.md`

> **Important:** This plan describes a **standalone repository** named `WinSuperWhisper`. It is **not** built inside the firstmate repo - firstmate only holds this plan and the spec. Create `WinSuperWhisper` as its own repo (Phase 1, Task 0 of [`phase1/01-foundation.md`](./phase1/01-foundation.md)).

---

## Why six files instead of one

This Phase 1 is not poured as one slab - it is built like a house, foundation up, in six logical pieces. Each piece is an independently verifiable plan with its own failing-test-first cycle, its own verification command, and its own binary exit conditions. The visual rationale (house cross-section, the compiler boundary, the governance and commit model) is captured alongside this file: [`2026-06-22-winsuperwhisper-phase1-split.html`](./2026-06-22-winsuperwhisper-phase1-split.html).

```
                        roof - built last
  ┌─────────────────────────────────────────────────────┐
  │ 5  Move-in    App composition + daemon lifecycle + e2e │  WIN11
  ├─────────────────────────────────────────────────────┤
  │ 4  Rooms      WPF UI: overlay, settings, tray         │  WIN11
  ├─────────────────────────────────────────────────────┤
  │ 3  Wiring     Win32 + NAudio adapters                 │  WIN11
  ├ ─ ─ ─ ─ ─ ─ ─ compiler-enforced boundary ─ ─ ─ ─ ─ ─ ┤
  │ 2a Skeleton   WinSuperWhisper.Core      2b  Daemon    │  PODMAN
  ├─────────────────────────────────────────────────────┤
  │ 1  Foundation repo + two-project split + test harness │  PODMAN
  └─────────────────────────────────────────────────────┘
                          ground
```

## Build order and the six plans

| #   | Piece                                                                                                                       | Plan file                                              | Verified | Depends on |
| --- | --------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ | -------- | ---------- |
| 1   | **Foundation** - repo, solution, 4 projects, `run-tests.sh` dual-tier harness                                               | [`phase1/01-foundation.md`](./phase1/01-foundation.md) | PODMAN   | -          |
| 2a  | **Core skeleton** - interfaces, models, `WavEncoder`, `FrameProtocol`, `DaemonClient`, `DictationOrchestrator`              | [`phase1/02a-core.md`](./phase1/02a-core.md)           | PODMAN   | 1          |
| 2b  | **Python daemon** - framing, `READY`, WAV→float32, transcribe seam, `[EXIT]`+drop                                           | [`phase1/02b-daemon.md`](./phase1/02b-daemon.md)       | PODMAN   | 1          |
| 3   | **Adapters** - `Win32HotkeyService`, `NAudioCapture`, `Win32TextInjector` (+UIPI clipboard fallback), `Win32MonitorService` | [`phase1/03-adapters.md`](./phase1/03-adapters.md)     | WIN11    | 2a         |
| 4   | **UI** - `OverlayWindow` (red square + waveform, DPI placement), `SettingsWindow`, tray                                     | [`phase1/04-ui.md`](./phase1/04-ui.md)                 | WIN11    | 2a, 3      |
| 5   | **Move-in** - `App.xaml` wiring, `DaemonProcessManager` (async `wsl.exe` launch), startup flow, full e2e                    | [`phase1/05-movein.md`](./phase1/05-movein.md)         | WIN11    | 3, 4       |

**Parallelism:** 2a and 2b rest only on the foundation and share no code - build them in parallel. Everything below the compiler boundary (1, 2a, 2b) is proven on this Linux machine in Podman before anyone touches the Win11 box (3, 4, 5). Each piece ships as its own PR.

---

## The contract that keeps the six files consistent

Every plan file uses these names, signatures, and the wire format verbatim. They are restated in each file where used; this is the single reference if anything looks inconsistent.

### Core interfaces (`WinSuperWhisper.Core.Interfaces`)

```csharp
public interface IHotkeyService : IDisposable {
    event EventHandler? Pressed;
    event EventHandler? Released;
    void Register(HotkeyCombo combo);
    void Unregister();
    bool IsArmed { get; }
    void SetArmed(bool armed);          // false until daemon READY
}
public interface IAudioCapture : IDisposable {
    event EventHandler<AudioLevel>? LevelAvailable;   // ~30fps amplitude
    void Start(); void Stop();
    byte[] GetCapturedPcm();            // 16 kHz mono 16-bit LE PCM, no header
    bool IsCapturing { get; }
}
public interface ITextInjector { InjectionResult Inject(string text); }
public interface IMonitorService {
    IReadOnlyList<MonitorInfo> GetMonitors();
    MonitorInfo? FindById(string id);
}
public interface IDaemonClient : IAsyncDisposable {
    event EventHandler? Disconnected;
    bool IsReady { get; }
    Task ConnectAsync(CancellationToken ct);          // connects then awaits READY
    Task<string> TranscribeAsync(byte[] wavBytes, CancellationToken ct);
    Task ShutdownAsync();                              // sends [EXIT], closes socket
}
```

### IPC wire format (fixed)

- Persistent TCP. Daemon binds `0.0.0.0:8765`; C# client connects `127.0.0.1:8765`.
- Every message is a frame: `[4-byte little-endian uint32 length N][N payload bytes]`.
- Frames disambiguated by payload content (no type byte):
  - **READY** (daemon→client): payload is exactly `READY` (5 ASCII bytes), sent once after the model loads, before any transcription is accepted.
  - **Transcribe request** (client→daemon): payload is a complete in-memory WAV (begins `RIFF`).
  - **Transcript response** (daemon→client): payload is UTF-8 transcript text (may be empty).
  - **EXIT** (client→daemon): payload is exactly `[EXIT]` (6 ASCII bytes); daemon closes and exits.
- Backstop: if the connection drops without `[EXIT]`, the daemon also exits (no zombie).

### Daemon facts

- Launched: `wsl.exe -d <distro> -e python3 <linux-path>/whisper_daemon.py --model <linux-model-dir> --host 0.0.0.0 --port 8765 [--language auto]`.
- faster-whisper model arg is a **directory** (CTranslate2), stays resident in RAM.
- Incoming WAV parsed with the stdlib `wave` module into a numpy `float32` array normalized by `/32768.0`. No soundfile/scipy/ffmpeg. `requirements.txt` = `faster-whisper`, `numpy` only.

(The full contract, including every model record and the file tree, is restated inside each plan file.)

---

## How each agent stays in shape and in step

An agent drifts only when "done" is a judgment call. This plan removes the judgment call: every step has a machine-checkable definition of done and one source of truth (the spec) it is not allowed to rewrite.

1. **Test-first, red→green.** The failing test is written before the code; success is objective.
2. **One gate: `run-tests.sh` green.** No step is done until the suite is green - the agent cannot self-certify.
3. **The compiler is a standing referee.** The Core/App split makes it physically impossible to smuggle Windows code into the Linux-tested layer.
4. **Bounded sessions, explicit checkpoints.** work → test → verify → checkpoint → stop; never continue from a state you cannot describe back.
5. **The spec is fixed; plans only decompose it.** Each plan cites the spec by absolute path and never redesigns - that keeps all phases consistent.
6. **Interfaces are the contract between phases.** Phase 1 defines all five; later phases build behind them.

## Exit conditions and the escalation rule

Each piece has **binary** exit conditions - all must be green; partial is not done. The moment a condition can't be met, the agent **stops and escalates**. It does not weaken a test, guess a spec detail, or work around the gate.

**Escalate-now triggers (no retry-loop, surface immediately):** a spec detail is ambiguous (wire format, frame layout, model strategy) · an exit condition is still red after **2 attempts** · anything needing a credential, the Win11 machine, or a decision · any temptation to relax a test to make it pass. Bounded retry (2 attempts) is only for mechanical failures (flaky build, transient I/O); judgment calls escalate on attempt one.

Per-piece exit conditions are listed at the end of each plan file. Summary:

| #   | Exit conditions (all green)                                                                                                                                                          |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | `dotnet build` of Core succeeds on Linux · 4 projects, correct TFMs · `run-tests.sh` exits 0 and reaches both tiers                                                                  |
| 2a  | All 5 interfaces compile · xUnit green in Podman (config, `WavEncoder`, `FrameProtocol`, orchestrator) · IPC-client tests cover READY gate, req/resp, reconnect, `[EXIT]`            |
| 2b  | pytest green in Podman (protocol, READY, `[EXIT]`+drop) · WAV→numpy via stdlib `wave` on a fixture · known WAV round-trips to a deterministic (fake-model) transcript                |
| 3   | `.App.Tests` Win32 adapter tests green on Win11 · SendInput-0 → clipboard fallback proven with a forced 0-return · mic capture yields 16 kHz mono PCM                                |
| 4   | UI smoke green on Win11 (overlay appears/positions/dismisses) · 48px-above-taskbar gap correct at 100/125/150% DPI (pure-function test) · settings persist to `%APPDATA%`            |
| 5   | Full e2e on Win11 (hold→speak→transcript typed into a real window) · daemon launches **async** (no UI hang), READY gates the hotkey · `[EXIT]` on close leaves no zombie WSL process |

## Commit cadence

The commit boundary is the green checkpoint, not the clock. Commit at every green; never commit a red tree. One commit per unit (an interface + its test, a protocol frame + its test, the WAV encoder + its test) ≈ 4-8 small conventional-message commits per piece, pushed after each. Each piece lands as its own PR over the green gate. Because no commit is broken: every commit is a recovery point, `git bisect` always lands on a real regression, and the history cannot accumulate broken or off-spec state.

## One execution detail to watch (Move-in)

The WSL daemon is a **persistent server**. Launch it asynchronously / non-blocking: `Process.Start` with `UseShellExecute = false`, and never `WaitForExit` on the UI thread - otherwise the WPF app hangs on launch. This is called out and test-guarded in [`phase1/05-movein.md`](./phase1/05-movein.md).
