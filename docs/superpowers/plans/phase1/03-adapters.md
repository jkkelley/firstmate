# Phase 1 - Win32 + NAudio Adapters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the real Windows adapters in `WinSuperWhisper.App` that satisfy the Core interfaces verbatim - global hotkey (Win32 `RegisterHotKey` + `GetAsyncKeyState` release polling), NAudio mic capture at 16 kHz mono 16-bit, `SendInput` text injection with a UIPI-safe clipboard fallback, and `EnumDisplayMonitors`-based monitor enumeration with DPI scale.

**Architecture:** Each adapter is a thin class in `WinSuperWhisper.App` implementing one Core interface. Every P/Invoke that drives a branch we must test (notably `SendInput`) is seamed behind an `internal` delegate so the branch is unit-testable without privileged setup; everything else is tested against the real Win32/NAudio surface on the Windows machine. The Core project (and the Podman test tier) never references any of this code - it lives in the `net8.0-windows` `WinSuperWhisper.App` project and is tested in `tests/WinSuperWhisper.App.Tests` (`net8.0-windows`).

**Tech Stack:** .NET 8 (`net8.0-windows`), WPF host process, NAudio (WASAPI/WaveIn), Win32 user32/shcore P/Invoke, xUnit + Moq, executed on real Windows 11 via `powershell.exe` invoked from WSL.

---

## TIER: WIN11 (this entire file)

**The Podman tier CANNOT run any task in this file. That is by design.**
Every task here targets `net8.0-windows` and links against Win32 user32/shcore and NAudio. `WinSuperWhisper.App` does not build on Linux, so `tests/WinSuperWhisper.App.Tests` does not build or run under Podman. The Podman tier covers Core + Python only (see `01-foundation`, `02a-core`, `02b-daemon`); the `FM_SKIP_WIN=1` switch in `scripts/run-tests.sh` exists precisely so Podman-only iteration skips this tier loudly rather than pretending to cover it.

These adapter tests run on a real Windows 11 machine. From WSL you invoke them through `powershell.exe`:

```bash
powershell.exe -File scripts/win-tests.ps1
```

`scripts/win-tests.ps1` (created in `01-foundation`) runs `dotnet test` against `tests/WinSuperWhisper.App.Tests` on the Windows side. Green looks like this in the WSL terminal (output streamed from PowerShell):

```
Passed!  - Failed:     0, Passed:    NN, Skipped:     S, Total:    NN+S, Duration: ...
```

A non-zero exit from `powershell.exe` means the Windows tier failed; `run-tests.sh` propagates that as a non-zero overall exit. Per-task "Run" commands below show the focused `dotnet test --filter` form to run inside that same PowerShell context (i.e. as a line you would add to / run via `win-tests.ps1` while iterating); the full-suite gate is always the single `powershell.exe -File scripts/win-tests.ps1` invocation above.

> **Where `dotnet` runs:** Per-task `dotnet test` commands are Windows-side commands. Run them through `powershell.exe -Command "dotnet test ..."` from WSL, or in a Windows shell directly. They are NOT Linux `dotnet` invocations - `net8.0-windows` will not restore or build on Linux.

---

## Spec reference

Behavior is governed by the design spec (absolute path, standalone repo - this plan does NOT live under the repo it builds):
`/home/luna/projects/firstmate/docs/superpowers/specs/2026-06-22-winsuperwhisper-design.md`

The relevant spec sections: Architecture > Components (Win32 hotkey, NAudio 16 kHz mono, `SendInput`, monitor detection), Data Flow > Recording and Transcription (steps 1-4), Failure Paths (SendInput / UIPI / clipboard fallback), and UI Design > Recording Overlay (DPI-aware positioning needs `MonitorInfo.DpiScale` and the work area from this adapter).

## Dependency and unlock

- **Depends on:** `02a-core` - the interfaces (`IHotkeyService`, `IAudioCapture`, `ITextInjector`, `IMonitorService`) and the models (`HotkeyCombo`, `AudioLevel`, `InjectionResult`, `MonitorInfo`) MUST already exist in `WinSuperWhisper.Core` with the exact signatures reproduced below. This plan implements those interfaces verbatim; do not re-declare or alter them.
- **Also depends on:** `01-foundation` - the `WinSuperWhisper.App` (`net8.0-windows`) project, the `tests/WinSuperWhisper.App.Tests` (`net8.0-windows`) project referencing App, and `scripts/win-tests.ps1`.
- **Unlocks:** `04-ui` - the overlay uses `IMonitorService.GetMonitors()`/`FindById` + `MonitorInfo.DpiScale`/work area for DPI-aware positioning, `IAudioCapture.LevelAvailable` to drive the waveform, and `IHotkeyService` press/release to start/stop. `05-movein` wires all four adapters into `App.xaml.cs`.

---

## Escalation contract (binary exit conditions; read before starting)

- **Exit conditions are binary and all must be green** (see the final checklist). "Mostly works" is failure.
- **Mechanical failure** (a flaky build, a transient NuGet restore error, a `dotnet test` that crashed on infrastructure rather than an assertion): retry up to **2 times**, then escalate with the exact error.
- **Any judgment call stops and escalates immediately - do not improvise.** Specifically:
  - A Win32 behavior that cannot be made deterministic in a unit test (e.g. the genuine UIPI block requires a real elevated foreground window). Do not fake elevation, do not auto-elevate, do not weaken the assertion. Mark it as a documented **manual-verification** step (this plan already does so for the real UIPI case) and escalate if you are tempted to do otherwise.
  - Anything requiring the app to run **elevated** to verify. Stop and escalate - never add an elevation manifest or `runas` to make a test pass.
  - Any ambiguity in the spec, a missing interface/model from `02a-core`, or any temptation to weaken, `[Skip]` silently, or delete a test. Stop and escalate.
- **A documented manual-verification step is NOT a silently-skipped test.** It is an `xUnit` `[Fact(Skip="...")]` with a precise human procedure in the skip reason, or a checklist item in this plan. It is visible and counted as Skipped in the run output.

---

## Core interfaces and models (from `02a-core` - reproduced verbatim, DO NOT redefine)

These already exist in `WinSuperWhisper.Core`. The adapters implement them exactly.

```csharp
namespace WinSuperWhisper.Core.Interfaces;

public interface IHotkeyService : IDisposable
{
    event EventHandler? Pressed;
    event EventHandler? Released;
    void Register(HotkeyCombo combo);
    void Unregister();
    bool IsArmed { get; }
    void SetArmed(bool armed);   // false until daemon READY
}

public interface IAudioCapture : IDisposable
{
    event EventHandler<AudioLevel>? LevelAvailable;   // ~30fps amplitude for waveform
    void Start();
    void Stop();
    byte[] GetCapturedPcm();     // 16 kHz mono 16-bit little-endian PCM, no header
    bool IsCapturing { get; }
}

public interface ITextInjector
{
    InjectionResult Inject(string text);
}

public interface IMonitorService
{
    IReadOnlyList<MonitorInfo> GetMonitors();
    MonitorInfo? FindById(string id);
}
```

```csharp
namespace WinSuperWhisper.Core.Models;

public sealed record HotkeyCombo(uint Modifiers, uint VirtualKey)
{
    public static HotkeyCombo Default => new(0x0001 /*MOD_ALT*/, 0x20 /*VK_SPACE*/);
}

public sealed record MonitorInfo(
    string Id, string Name, int WidthPx, int HeightPx, double DpiScale,
    int WorkAreaLeft, int WorkAreaTop, int WorkAreaRight, int WorkAreaBottom,
    bool IsPrimary);

public readonly record struct AudioLevel(float Peak);   // normalized 0.0..1.0

public enum InjectionResult { Typed, ClipboardFallback, Failed }
```

---

## File structure for this plan

- Create `src/WinSuperWhisper.App/Win32/NativeMethods.cs` - shared P/Invoke surface (user32/shcore signatures) used by the adapters. One responsibility: native interop declarations.
- Create `src/WinSuperWhisper.App/Win32/Win32HotkeyService.cs` - `IHotkeyService` via `RegisterHotKey` + a message-only window for `WM_HOTKEY` (press edge) + `GetAsyncKeyState` polling for the release edge; `SetArmed` gates event raising.
- Create `src/WinSuperWhisper.App/Audio/NAudioCapture.cs` - `IAudioCapture` via NAudio `WaveInEvent` at 16 kHz mono 16-bit; buffers PCM for `GetCapturedPcm()`; raises `LevelAvailable` ~30 fps with a normalized peak.
- Create `src/WinSuperWhisper.App/Win32/Win32TextInjector.cs` - `ITextInjector` via `SendInput` Unicode; on `SendInput` returning 0, falls through to clipboard + Ctrl+V (`InjectionResult.ClipboardFallback`); `SendInput` seamed behind an `internal` delegate for the fallback unit test.
- Create `src/WinSuperWhisper.App/Win32/Win32MonitorService.cs` - `IMonitorService` via `EnumDisplayMonitors` + `GetMonitorInfo` + `GetDpiForMonitor`; populates `MonitorInfo` exactly.
- Create test files under `tests/WinSuperWhisper.App.Tests/` (one per adapter).
- Add `<InternalsVisibleTo>` so the test project can reach the `internal` seams.

NAudio is referenced by `WinSuperWhisper.App` only (added in `01-foundation`; if absent, see Task 0).

---

### Task 0: Confirm NAudio package and InternalsVisibleTo (prerequisite wiring)

**Files:**

- Modify: `src/WinSuperWhisper.App/WinSuperWhisper.App.csproj`

- [ ] **Step 1: Ensure NAudio is referenced and tests can see internals**

Open `src/WinSuperWhisper.App/WinSuperWhisper.App.csproj`. Ensure it has `<Nullable>enable</Nullable>`, references NAudio, and exposes internals to the test assembly. If NAudio is already present from `01-foundation`, only add the `InternalsVisibleTo` item group. The file should contain (merge, do not duplicate existing nodes):

```xml
<Project Sdk="Microsoft.NET.Sdk">

  <PropertyGroup>
    <OutputType>WinExe</OutputType>
    <TargetFramework>net8.0-windows</TargetFramework>
    <UseWPF>true</UseWPF>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
  </PropertyGroup>

  <ItemGroup>
    <PackageReference Include="NAudio" Version="2.2.1" />
  </ItemGroup>

  <ItemGroup>
    <ProjectReference Include="..\WinSuperWhisper.Core\WinSuperWhisper.Core.csproj" />
  </ItemGroup>

  <ItemGroup>
    <InternalsVisibleTo Include="WinSuperWhisper.App.Tests" />
  </ItemGroup>

</Project>
```

- [ ] **Step 2: Verify the App project restores and builds on Windows**

Run (Windows-side, via PowerShell from WSL):
`powershell.exe -Command "dotnet build src/WinSuperWhisper.App/WinSuperWhisper.App.csproj -c Debug"`
Expected: `Build succeeded.` with 0 errors. (If NAudio restore fails, that is a mechanical failure - retry once, then escalate.)

- [ ] **Step 3: Commit**

```bash
git add src/WinSuperWhisper.App/WinSuperWhisper.App.csproj
git commit -m "build: wire NAudio + InternalsVisibleTo for App adapters"
```

---

### Task 1: Native interop surface (NativeMethods)

**Files:**

- Create: `src/WinSuperWhisper.App/Win32/NativeMethods.cs`

No test of its own (it is pure P/Invoke declarations exercised by every adapter test that follows). It is committed with Task 2 so the tree never holds a referenced-but-uncommitted file.

- [ ] **Step 1: Write the full native surface**

Create `src/WinSuperWhisper.App/Win32/NativeMethods.cs`:

```csharp
using System;
using System.Runtime.InteropServices;

namespace WinSuperWhisper.App.Win32;

/// <summary>
/// All Win32 P/Invoke declarations used by the App adapters.
/// Kept in one place so the interop surface is auditable and the
/// individual adapters stay focused on behavior.
/// </summary>
internal static class NativeMethods
{
    // ----- Hotkey (user32) -----

    public const int WM_HOTKEY = 0x0312;
    public const uint MOD_NOREPEAT = 0x4000;

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool RegisterHotKey(IntPtr hWnd, int id, uint fsModifiers, uint vk);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool UnregisterHotKey(IntPtr hWnd, int id);

    [DllImport("user32.dll")]
    public static extern short GetAsyncKeyState(int vKey);

    // ----- SendInput (user32) -----

    public const uint INPUT_KEYBOARD = 1;
    public const uint KEYEVENTF_KEYUP = 0x0002;
    public const uint KEYEVENTF_UNICODE = 0x0004;
    public const ushort VK_CONTROL = 0x11;
    public const ushort VK_V = 0x56;

    [StructLayout(LayoutKind.Sequential)]
    public struct KEYBDINPUT
    {
        public ushort wVk;
        public ushort wScan;
        public uint dwFlags;
        public uint time;
        public IntPtr dwExtraInfo;
    }

    [StructLayout(LayoutKind.Explicit)]
    public struct INPUTUNION
    {
        [FieldOffset(0)] public KEYBDINPUT ki;
        // MOUSEINPUT / HARDWAREINPUT are larger on x64; pad the union to the
        // largest member so the struct size matches what SendInput expects.
        [FieldOffset(0)] private readonly long _pad0;
        [FieldOffset(8)] private readonly long _pad1;
        [FieldOffset(16)] private readonly long _pad2;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct INPUT
    {
        public uint type;
        public INPUTUNION u;
    }

    /// <summary>
    /// Returns the number of events successfully inserted. A return of 0
    /// means the input was blocked (e.g. UIPI when an elevated window is
    /// foreground). cbSize must be Marshal.SizeOf&lt;INPUT&gt;().
    /// </summary>
    [DllImport("user32.dll", SetLastError = true)]
    public static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);

    // ----- Monitor enumeration (user32 / shcore) -----

    [StructLayout(LayoutKind.Sequential)]
    public struct RECT
    {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }

    public const int CCHDEVICENAME = 32;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct MONITORINFOEX
    {
        public int cbSize;
        public RECT rcMonitor;
        public RECT rcWork;
        public uint dwFlags;

        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = CCHDEVICENAME)]
        public string szDevice;
    }

    public const uint MONITORINFOF_PRIMARY = 0x00000001;

    // MDT_EFFECTIVE_DPI = 0
    public const int MDT_EFFECTIVE_DPI = 0;

    public delegate bool MonitorEnumProc(IntPtr hMonitor, IntPtr hdc, ref RECT lprcMonitor, IntPtr dwData);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool EnumDisplayMonitors(IntPtr hdc, IntPtr lprcClip, MonitorEnumProc lpfnEnum, IntPtr dwData);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool GetMonitorInfo(IntPtr hMonitor, ref MONITORINFOEX lpmi);

    [DllImport("Shcore.dll")]
    public static extern int GetDpiForMonitor(IntPtr hmonitor, int dpiType, out uint dpiX, out uint dpiY);
}
```

This file has no test of its own; commit it alongside the first adapter that uses it.

---

### Task 2: Win32TextInjector - SendInput with seamed clipboard fallback

This adapter is implemented first because its critical branch (SendInput returns 0 -> clipboard fallback) is the highest-value deterministic test in the file and proves the seam pattern.

**Files:**

- Create: `src/WinSuperWhisper.App/Win32/Win32TextInjector.cs`
- Test: `tests/WinSuperWhisper.App.Tests/Win32TextInjectorTests.cs`

- [ ] **Step 1: Write the failing test**

Create `tests/WinSuperWhisper.App.Tests/Win32TextInjectorTests.cs`:

```csharp
using System;
using WinSuperWhisper.App.Win32;
using WinSuperWhisper.Core.Interfaces;
using WinSuperWhisper.Core.Models;
using Xunit;

namespace WinSuperWhisper.App.Tests;

public class Win32TextInjectorTests
{
    [Fact]
    public void Inject_WhenSendInputSucceeds_ReturnsTyped()
    {
        // Fake SendInput reports it inserted every requested event.
        uint FakeSendInput(uint n, NativeMethods.INPUT[] inputs, int cb) => n;
        string? clipboardSet = null;

        var injector = new Win32TextInjector(
            sendInput: FakeSendInput,
            setClipboard: text => clipboardSet = text);

        InjectionResult result = injector.Inject("hello");

        Assert.Equal(InjectionResult.Typed, result);
        Assert.Null(clipboardSet); // fallback must not run on success
    }

    [Fact]
    public void Inject_WhenSendInputReturnsZero_FallsBackToClipboardAndReturnsClipboardFallback()
    {
        // First SendInput call (the Unicode typing) returns 0 -> UIPI blocked.
        // The fallback then sets the clipboard and sends Ctrl+V (also via SendInput).
        int calls = 0;
        string? clipboardSet = null;

        uint FakeSendInput(uint n, NativeMethods.INPUT[] inputs, int cb)
        {
            calls++;
            // First call (typing) is blocked. The Ctrl+V key sequence in the
            // fallback is allowed to "succeed" so we can prove we reached it.
            return calls == 1 ? 0u : n;
        }

        var injector = new Win32TextInjector(
            sendInput: FakeSendInput,
            setClipboard: text => clipboardSet = text);

        InjectionResult result = injector.Inject("blocked text");

        Assert.Equal(InjectionResult.ClipboardFallback, result);
        Assert.Equal("blocked text", clipboardSet);
        Assert.True(calls >= 2, "fallback should have attempted a Ctrl+V SendInput");
    }

    [Fact]
    public void Inject_WhenSendInputAndClipboardPasteBothFail_ReturnsFailed()
    {
        // Every SendInput returns 0 -> typing blocked AND Ctrl+V blocked.
        uint FakeSendInput(uint n, NativeMethods.INPUT[] inputs, int cb) => 0u;
        string? clipboardSet = null;

        var injector = new Win32TextInjector(
            sendInput: FakeSendInput,
            setClipboard: text => clipboardSet = text);

        InjectionResult result = injector.Inject("nothing works");

        // Clipboard was still set (best effort), but the paste keystroke was
        // also blocked, so we cannot claim success: report Failed.
        Assert.Equal(InjectionResult.Failed, result);
        Assert.Equal("nothing works", clipboardSet);
    }

    [Fact]
    public void Inject_EmptyString_ReturnsTypedWithoutCallingSendInput()
    {
        int calls = 0;
        uint FakeSendInput(uint n, NativeMethods.INPUT[] inputs, int cb) { calls++; return n; }

        var injector = new Win32TextInjector(
            sendInput: FakeSendInput,
            setClipboard: _ => { });

        InjectionResult result = injector.Inject("");

        Assert.Equal(InjectionResult.Typed, result);
        Assert.Equal(0, calls);
    }

    // MANUAL VERIFICATION (cannot be made deterministic in a unit test):
    // A genuine UIPI block requires a real elevated foreground window AND a
    // non-elevated WinSuperWhisper. Reproducing that needs Administrator setup,
    // so it is a documented manual step, not an automated test:
    //   1. Run WinSuperWhisper non-elevated.
    //   2. Open an elevated (Run as administrator) PowerShell and focus it.
    //   3. Trigger an injection; SendInput returns 0; observe the transcript
    //      arriving via the Ctrl+V clipboard fallback (InjectionResult.ClipboardFallback).
    // Do NOT auto-elevate to make this pass. Escalate if tempted.
    [Fact(Skip = "Manual: requires a real elevated foreground window; see comment above. Do not auto-elevate.")]
    public void Inject_IntoElevatedForegroundWindow_UsesClipboardFallback_MANUAL() { }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run (Windows-side): `powershell.exe -Command "dotnet test tests/WinSuperWhisper.App.Tests --filter FullyQualifiedName~Win32TextInjectorTests"`
Expected: FAIL to compile - `Win32TextInjector` does not exist / has no such constructor.

- [ ] **Step 3: Write minimal implementation**

Create `src/WinSuperWhisper.App/Win32/Win32TextInjector.cs`:

```csharp
using System;
using System.Runtime.InteropServices;
using System.Windows;
using WinSuperWhisper.Core.Interfaces;
using WinSuperWhisper.Core.Models;

namespace WinSuperWhisper.App.Win32;

/// <summary>
/// Injects text into the foreground window via SendInput Unicode keystrokes.
/// If SendInput is blocked (returns 0 - e.g. UIPI on an elevated foreground
/// window), falls back to clipboard + Ctrl+V. We deliberately never elevate.
/// </summary>
public sealed class Win32TextInjector : ITextInjector
{
    /// <summary>Seam over user32 SendInput so the fallback branch is unit-testable.</summary>
    internal delegate uint SendInputFunc(uint nInputs, NativeMethods.INPUT[] pInputs, int cbSize);

    private readonly SendInputFunc _sendInput;
    private readonly Action<string> _setClipboard;

    /// <summary>Production constructor: real SendInput + real WPF clipboard.</summary>
    public Win32TextInjector()
        : this(RealSendInput, SetClipboardText)
    {
    }

    /// <summary>Test/seam constructor.</summary>
    internal Win32TextInjector(SendInputFunc sendInput, Action<string> setClipboard)
    {
        _sendInput = sendInput;
        _setClipboard = setClipboard;
    }

    public InjectionResult Inject(string text)
    {
        if (string.IsNullOrEmpty(text))
        {
            return InjectionResult.Typed; // nothing to type, trivially "typed"
        }

        if (TryTypeUnicode(text))
        {
            return InjectionResult.Typed;
        }

        // SendInput was blocked. Best-effort clipboard + Ctrl+V.
        _setClipboard(text);
        return TrySendCtrlV()
            ? InjectionResult.ClipboardFallback
            : InjectionResult.Failed;
    }

    /// <summary>
    /// Sends the text as Unicode key events. Returns false if SendInput is
    /// blocked (any event returns 0 inserted).
    /// </summary>
    private bool TryTypeUnicode(string text)
    {
        var inputs = new NativeMethods.INPUT[text.Length * 2];
        int i = 0;
        foreach (char c in text)
        {
            inputs[i++] = UnicodeKey(c, keyUp: false);
            inputs[i++] = UnicodeKey(c, keyUp: true);
        }

        int size = Marshal.SizeOf<NativeMethods.INPUT>();
        uint sent = _sendInput((uint)inputs.Length, inputs, size);
        return sent == (uint)inputs.Length;
    }

    private bool TrySendCtrlV()
    {
        var inputs = new[]
        {
            VkKey(NativeMethods.VK_CONTROL, keyUp: false),
            VkKey(NativeMethods.VK_V, keyUp: false),
            VkKey(NativeMethods.VK_V, keyUp: true),
            VkKey(NativeMethods.VK_CONTROL, keyUp: true),
        };

        int size = Marshal.SizeOf<NativeMethods.INPUT>();
        uint sent = _sendInput((uint)inputs.Length, inputs, size);
        return sent == (uint)inputs.Length;
    }

    private static NativeMethods.INPUT UnicodeKey(char c, bool keyUp) => new()
    {
        type = NativeMethods.INPUT_KEYBOARD,
        u = new NativeMethods.INPUTUNION
        {
            ki = new NativeMethods.KEYBDINPUT
            {
                wVk = 0,
                wScan = c,
                dwFlags = NativeMethods.KEYEVENTF_UNICODE |
                          (keyUp ? NativeMethods.KEYEVENTF_KEYUP : 0),
                time = 0,
                dwExtraInfo = IntPtr.Zero,
            },
        },
    };

    private static NativeMethods.INPUT VkKey(ushort vk, bool keyUp) => new()
    {
        type = NativeMethods.INPUT_KEYBOARD,
        u = new NativeMethods.INPUTUNION
        {
            ki = new NativeMethods.KEYBDINPUT
            {
                wVk = vk,
                wScan = 0,
                dwFlags = keyUp ? NativeMethods.KEYEVENTF_KEYUP : 0,
                time = 0,
                dwExtraInfo = IntPtr.Zero,
            },
        },
    };

    private static uint RealSendInput(uint n, NativeMethods.INPUT[] inputs, int cb)
        => NativeMethods.SendInput(n, inputs, cb);

    [System.Runtime.Versioning.SupportedOSPlatform("windows")]
    private static void SetClipboardText(string text)
    {
        // WPF clipboard must run on an STA thread. The App's injection path
        // runs on the UI thread; for safety this is wrapped by callers, and
        // tests inject their own delegate so this body is not exercised off-UI.
        Clipboard.SetText(text);
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run (Windows-side): `powershell.exe -Command "dotnet test tests/WinSuperWhisper.App.Tests --filter FullyQualifiedName~Win32TextInjectorTests"`
Expected: PASS - 4 passed, 1 skipped (the manual UIPI fact).

- [ ] **Step 5: Commit**

```bash
git add src/WinSuperWhisper.App/Win32/NativeMethods.cs \
        src/WinSuperWhisper.App/Win32/Win32TextInjector.cs \
        tests/WinSuperWhisper.App.Tests/Win32TextInjectorTests.cs
git commit -m "feat: Win32TextInjector with SendInput-0 clipboard fallback"
```

---

### Task 3: Win32MonitorService - EnumDisplayMonitors + DPI

**Files:**

- Create: `src/WinSuperWhisper.App/Win32/Win32MonitorService.cs`
- Test: `tests/WinSuperWhisper.App.Tests/Win32MonitorServiceTests.cs`

This adapter reads the real desktop, so the test asserts invariants that hold on any Windows 11 machine (at least one monitor, sane DPI scale, non-empty work area, exactly one primary) rather than exact pixel values.

- [ ] **Step 1: Write the failing test**

Create `tests/WinSuperWhisper.App.Tests/Win32MonitorServiceTests.cs`:

```csharp
using System.Linq;
using WinSuperWhisper.App.Win32;
using WinSuperWhisper.Core.Interfaces;
using WinSuperWhisper.Core.Models;
using Xunit;

namespace WinSuperWhisper.App.Tests;

public class Win32MonitorServiceTests
{
    private readonly IMonitorService _svc = new Win32MonitorService();

    [Fact]
    public void GetMonitors_ReturnsAtLeastOne()
    {
        var monitors = _svc.GetMonitors();
        Assert.NotEmpty(monitors);
    }

    [Fact]
    public void GetMonitors_EachHasSaneDpiScaleAndWorkArea()
    {
        foreach (MonitorInfo m in _svc.GetMonitors())
        {
            // DPI scale is 1.0 at 96 DPI; bounded sanity range covers
            // 100%..400% scaling without asserting a specific machine.
            Assert.InRange(m.DpiScale, 0.5, 4.0);

            // Work area must be a non-degenerate rectangle.
            Assert.True(m.WorkAreaRight > m.WorkAreaLeft, "work area width > 0");
            Assert.True(m.WorkAreaBottom > m.WorkAreaTop, "work area height > 0");

            Assert.True(m.WidthPx > 0);
            Assert.True(m.HeightPx > 0);
            Assert.False(string.IsNullOrWhiteSpace(m.Id));
        }
    }

    [Fact]
    public void GetMonitors_HasExactlyOnePrimary()
    {
        int primaries = _svc.GetMonitors().Count(m => m.IsPrimary);
        Assert.Equal(1, primaries);
    }

    [Fact]
    public void FindById_ReturnsMatchingMonitor_ForKnownId()
    {
        var first = _svc.GetMonitors().First();
        var found = _svc.FindById(first.Id);
        Assert.NotNull(found);
        Assert.Equal(first.Id, found!.Id);
    }

    [Fact]
    public void FindById_ReturnsNull_ForUnknownId()
    {
        var found = _svc.FindById(@"\\.\NO_SUCH_DISPLAY_999");
        Assert.Null(found);
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run (Windows-side): `powershell.exe -Command "dotnet test tests/WinSuperWhisper.App.Tests --filter FullyQualifiedName~Win32MonitorServiceTests"`
Expected: FAIL to compile - `Win32MonitorService` does not exist.

- [ ] **Step 3: Write minimal implementation**

Create `src/WinSuperWhisper.App/Win32/Win32MonitorService.cs`:

```csharp
using System;
using System.Collections.Generic;
using WinSuperWhisper.Core.Interfaces;
using WinSuperWhisper.Core.Models;

namespace WinSuperWhisper.App.Win32;

/// <summary>
/// Enumerates physical monitors via EnumDisplayMonitors, reading the work area
/// (taskbar-excluded) and effective DPI for each. DpiScale is dpiX/96.
/// </summary>
public sealed class Win32MonitorService : IMonitorService
{
    public IReadOnlyList<MonitorInfo> GetMonitors()
    {
        var result = new List<MonitorInfo>();

        bool Callback(IntPtr hMonitor, IntPtr hdc, ref NativeMethods.RECT rect, IntPtr data)
        {
            var info = new NativeMethods.MONITORINFOEX
            {
                cbSize = System.Runtime.InteropServices.Marshal.SizeOf<NativeMethods.MONITORINFOEX>(),
            };

            if (!NativeMethods.GetMonitorInfo(hMonitor, ref info))
            {
                return true; // skip this monitor, keep enumerating
            }

            double dpiScale = 1.0;
            if (NativeMethods.GetDpiForMonitor(
                    hMonitor, NativeMethods.MDT_EFFECTIVE_DPI, out uint dpiX, out _) == 0
                && dpiX > 0)
            {
                dpiScale = dpiX / 96.0;
            }

            bool isPrimary = (info.dwFlags & NativeMethods.MONITORINFOF_PRIMARY) != 0;
            int widthPx = info.rcMonitor.Right - info.rcMonitor.Left;
            int heightPx = info.rcMonitor.Bottom - info.rcMonitor.Top;

            result.Add(new MonitorInfo(
                Id: info.szDevice,
                Name: info.szDevice,
                WidthPx: widthPx,
                HeightPx: heightPx,
                DpiScale: dpiScale,
                WorkAreaLeft: info.rcWork.Left,
                WorkAreaTop: info.rcWork.Top,
                WorkAreaRight: info.rcWork.Right,
                WorkAreaBottom: info.rcWork.Bottom,
                IsPrimary: isPrimary));

            return true;
        }

        NativeMethods.EnumDisplayMonitors(IntPtr.Zero, IntPtr.Zero, Callback, IntPtr.Zero);
        return result;
    }

    public MonitorInfo? FindById(string id)
    {
        foreach (MonitorInfo m in GetMonitors())
        {
            if (string.Equals(m.Id, id, StringComparison.OrdinalIgnoreCase))
            {
                return m;
            }
        }
        return null;
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run (Windows-side): `powershell.exe -Command "dotnet test tests/WinSuperWhisper.App.Tests --filter FullyQualifiedName~Win32MonitorServiceTests"`
Expected: PASS - 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/WinSuperWhisper.App/Win32/Win32MonitorService.cs \
        tests/WinSuperWhisper.App.Tests/Win32MonitorServiceTests.cs
git commit -m "feat: Win32MonitorService via EnumDisplayMonitors + GetDpiForMonitor"
```

---

### Task 4: NAudioCapture - 16 kHz mono 16-bit capture + level events

**Files:**

- Create: `src/WinSuperWhisper.App/Audio/NAudioCapture.cs`
- Test: `tests/WinSuperWhisper.App.Tests/NAudioCaptureTests.cs`

The capture device is seamed behind an `internal IWaveInDevice` so the buffering, format, and level-event logic are unit-testable by pushing synthetic `WaveInEventArgs`-equivalent buffers - no real microphone required. A separate, opt-in real-device smoke fact is provided and skipped by default (no mic guaranteed on a CI/headless box).

- [ ] **Step 1: Write the failing test**

Create `tests/WinSuperWhisper.App.Tests/NAudioCaptureTests.cs`:

```csharp
using System;
using System.Collections.Generic;
using WinSuperWhisper.App.Audio;
using WinSuperWhisper.Core.Interfaces;
using WinSuperWhisper.Core.Models;
using Xunit;

namespace WinSuperWhisper.App.Tests;

public class NAudioCaptureTests
{
    /// <summary>A fake capture device the test drives directly.</summary>
    private sealed class FakeWaveInDevice : IWaveInDevice
    {
        public event EventHandler<byte[]>? DataAvailable;
        public bool Recording { get; private set; }

        public void StartRecording() => Recording = true;
        public void StopRecording() => Recording = false;
        public void Dispose() { }

        public void PushPcm(byte[] pcm) => DataAvailable?.Invoke(this, pcm);
    }

    private static byte[] Sample16(short value)
        => new[] { (byte)(value & 0xFF), (byte)((value >> 8) & 0xFF) };

    [Fact]
    public void GetCapturedPcm_ReturnsAccumulatedBytesInOrder()
    {
        var fake = new FakeWaveInDevice();
        var capture = new NAudioCapture(fake);

        capture.Start();
        fake.PushPcm(new byte[] { 1, 2, 3, 4 });
        fake.PushPcm(new byte[] { 5, 6 });
        capture.Stop();

        Assert.Equal(new byte[] { 1, 2, 3, 4, 5, 6 }, capture.GetCapturedPcm());
    }

    [Fact]
    public void IsCapturing_TracksStartAndStop()
    {
        var fake = new FakeWaveInDevice();
        var capture = new NAudioCapture(fake);

        Assert.False(capture.IsCapturing);
        capture.Start();
        Assert.True(capture.IsCapturing);
        Assert.True(fake.Recording);
        capture.Stop();
        Assert.False(capture.IsCapturing);
        Assert.False(fake.Recording);
    }

    [Fact]
    public void Start_ResetsBufferFromPreviousCapture()
    {
        var fake = new FakeWaveInDevice();
        var capture = new NAudioCapture(fake);

        capture.Start();
        fake.PushPcm(new byte[] { 9, 9 });
        capture.Stop();

        capture.Start();
        fake.PushPcm(new byte[] { 1, 1 });
        capture.Stop();

        Assert.Equal(new byte[] { 1, 1 }, capture.GetCapturedPcm());
    }

    [Fact]
    public void LevelAvailable_RaisesNormalizedPeakBetweenZeroAndOne()
    {
        var fake = new FakeWaveInDevice();
        var capture = new NAudioCapture(fake);
        var peaks = new List<float>();
        capture.LevelAvailable += (_, lvl) => peaks.Add(lvl.Peak);

        capture.Start();
        // A full-scale negative sample (short.MinValue) => peak ~1.0
        fake.PushPcm(Sample16(short.MinValue));
        capture.Stop();

        Assert.NotEmpty(peaks);
        foreach (var p in peaks)
        {
            Assert.InRange(p, 0.0f, 1.0f);
        }
        Assert.True(peaks[^1] > 0.9f, "full-scale sample should peak near 1.0");
    }

    [Fact]
    public void LevelAvailable_SilenceProducesNearZeroPeak()
    {
        var fake = new FakeWaveInDevice();
        var capture = new NAudioCapture(fake);
        float last = -1f;
        capture.LevelAvailable += (_, lvl) => last = lvl.Peak;

        capture.Start();
        fake.PushPcm(Sample16(0)); // silence
        capture.Stop();

        Assert.InRange(last, 0.0f, 0.01f);
    }

    // OPT-IN real-device smoke test. Skipped by default because a headless /
    // CI Windows box may have no microphone. Run manually on a machine with a
    // mic to confirm NAudio yields 16 kHz mono 16-bit PCM end-to-end.
    [Fact(Skip = "Manual: requires a physical microphone. Confirms real 16kHz mono PCM capture.")]
    public void RealDevice_CapturesSixteenKMonoPcm_MANUAL()
    {
        using var capture = new NAudioCapture(); // real WaveInEvent device
        capture.Start();
        System.Threading.Thread.Sleep(500);
        capture.Stop();
        byte[] pcm = capture.GetCapturedPcm();
        // 16kHz mono 16-bit => 32000 bytes/sec; 500ms => roughly 16000 bytes.
        Assert.True(pcm.Length > 8000, $"expected substantial PCM, got {pcm.Length} bytes");
        Assert.Equal(0, pcm.Length % 2); // 16-bit samples => even byte count
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run (Windows-side): `powershell.exe -Command "dotnet test tests/WinSuperWhisper.App.Tests --filter FullyQualifiedName~NAudioCaptureTests"`
Expected: FAIL to compile - `NAudioCapture` and `IWaveInDevice` do not exist.

- [ ] **Step 3: Write minimal implementation**

Create `src/WinSuperWhisper.App/Audio/NAudioCapture.cs`:

```csharp
using System;
using System.Collections.Generic;
using NAudio.Wave;
using WinSuperWhisper.Core.Interfaces;
using WinSuperWhisper.Core.Models;

namespace WinSuperWhisper.App.Audio;

/// <summary>
/// Seam over a capture device so NAudioCapture's buffering/level logic is
/// unit-testable with a fake. DataAvailable carries the raw 16-bit PCM bytes
/// for one buffer.
/// </summary>
internal interface IWaveInDevice : IDisposable
{
    event EventHandler<byte[]>? DataAvailable;
    void StartRecording();
    void StopRecording();
}

/// <summary>Real NAudio WaveInEvent device at 16 kHz mono 16-bit.</summary>
internal sealed class NAudioWaveInDevice : IWaveInDevice
{
    public event EventHandler<byte[]>? DataAvailable;

    private readonly WaveInEvent _waveIn;

    public NAudioWaveInDevice()
    {
        _waveIn = new WaveInEvent
        {
            WaveFormat = new WaveFormat(16000, 16, 1), // 16 kHz, 16-bit, mono
            BufferMilliseconds = 33,                   // ~30 buffers/sec for ~30fps levels
        };
        _waveIn.DataAvailable += (_, e) =>
        {
            var copy = new byte[e.BytesRecorded];
            Array.Copy(e.Buffer, copy, e.BytesRecorded);
            DataAvailable?.Invoke(this, copy);
        };
    }

    public void StartRecording() => _waveIn.StartRecording();
    public void StopRecording() => _waveIn.StopRecording();
    public void Dispose() => _waveIn.Dispose();
}

/// <summary>
/// Captures microphone audio as 16 kHz mono 16-bit little-endian PCM, buffers
/// it for GetCapturedPcm(), and raises LevelAvailable (~30fps) with the
/// normalized peak amplitude of each buffer for the waveform UI.
/// </summary>
public sealed class NAudioCapture : IAudioCapture
{
    public event EventHandler<AudioLevel>? LevelAvailable;

    private readonly IWaveInDevice _device;
    private readonly List<byte> _buffer = new();
    private readonly object _gate = new();
    private bool _capturing;

    /// <summary>Production constructor: real NAudio device.</summary>
    public NAudioCapture()
        : this(new NAudioWaveInDevice())
    {
    }

    /// <summary>Test/seam constructor.</summary>
    internal NAudioCapture(IWaveInDevice device)
    {
        _device = device;
        _device.DataAvailable += OnData;
    }

    public bool IsCapturing => _capturing;

    public void Start()
    {
        lock (_gate)
        {
            _buffer.Clear();
            _capturing = true;
        }
        _device.StartRecording();
    }

    public void Stop()
    {
        _device.StopRecording();
        _capturing = false;
    }

    public byte[] GetCapturedPcm()
    {
        lock (_gate)
        {
            return _buffer.ToArray();
        }
    }

    private void OnData(object? sender, byte[] pcm)
    {
        lock (_gate)
        {
            _buffer.AddRange(pcm);
        }
        LevelAvailable?.Invoke(this, new AudioLevel(ComputePeak(pcm)));
    }

    /// <summary>Normalized peak (0..1) of a 16-bit little-endian PCM buffer.</summary>
    private static float ComputePeak(byte[] pcm)
    {
        int maxAbs = 0;
        for (int i = 0; i + 1 < pcm.Length; i += 2)
        {
            short sample = (short)(pcm[i] | (pcm[i + 1] << 8));
            int abs = sample == short.MinValue ? 32768 : Math.Abs(sample);
            if (abs > maxAbs)
            {
                maxAbs = abs;
            }
        }
        return maxAbs / 32768f;
    }

    public void Dispose()
    {
        _device.DataAvailable -= OnData;
        _device.Dispose();
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run (Windows-side): `powershell.exe -Command "dotnet test tests/WinSuperWhisper.App.Tests --filter FullyQualifiedName~NAudioCaptureTests"`
Expected: PASS - 5 passed, 1 skipped (the manual real-device fact).

- [ ] **Step 5: Commit**

```bash
git add src/WinSuperWhisper.App/Audio/NAudioCapture.cs \
        tests/WinSuperWhisper.App.Tests/NAudioCaptureTests.cs
git commit -m "feat: NAudioCapture 16kHz mono PCM with level events"
```

---

### Task 5: Win32HotkeyService - RegisterHotKey + GetAsyncKeyState release polling

**Files:**

- Create: `src/WinSuperWhisper.App/Win32/Win32HotkeyService.cs`
- Test: `tests/WinSuperWhisper.App.Tests/Win32HotkeyServiceTests.cs`

**Press/release approach for Phase 1 (justified).** `RegisterHotKey` only delivers `WM_HOTKEY` on the _press_ edge - Win32 has no built-in hotkey key-up notification. Two ways to detect the release edge:

1. A low-level keyboard hook (`WH_KEYBOARD_LL`). Global, intrusive, requires a hook procedure on the message-pumping thread, and is the kind of thing AV/EDR flags. Overkill for one key.
2. **`GetAsyncKeyState` polling** of the hotkey's virtual key, started on press and stopped when the key reads up. Self-contained, no global hook, trivially correct for hold-to-record.

**Phase 1 picks `GetAsyncKeyState` polling.** It is the smallest correct mechanism for "fire Released when the held key comes up", carries no global-hook risk, and matches the hold-to-record interaction exactly. (Phase 3's toggle mode does not even need release detection.)

The two halves are seamed for deterministic testing: the raw `WM_HOTKEY` arrival is exposed as `internal void OnHotKeyMessage()` (so a test can pump a synthetic press without a real window/message loop), and the release edge is exposed as `internal void PollReleaseOnce()` driving off an injectable `Func<int, bool> isKeyDown` (so a test can pump a synthetic release without a real keyboard). `SetArmed(false)` gates BOTH edges.

- [ ] **Step 1: Write the failing test**

Create `tests/WinSuperWhisper.App.Tests/Win32HotkeyServiceTests.cs`:

```csharp
using System;
using WinSuperWhisper.App.Win32;
using WinSuperWhisper.Core.Interfaces;
using WinSuperWhisper.Core.Models;
using Xunit;

namespace WinSuperWhisper.App.Tests;

public class Win32HotkeyServiceTests
{
    private static Win32HotkeyService NewSeamed(Func<int, bool> isKeyDown)
        => new(isKeyDown);

    [Fact]
    public void NewService_IsNotArmed()
    {
        using var svc = NewSeamed(_ => false);
        Assert.False(svc.IsArmed);
    }

    [Fact]
    public void SetArmed_TogglesIsArmed()
    {
        using var svc = NewSeamed(_ => false);
        svc.SetArmed(true);
        Assert.True(svc.IsArmed);
        svc.SetArmed(false);
        Assert.False(svc.IsArmed);
    }

    [Fact]
    public void HotKeyMessage_WhenArmed_RaisesPressed()
    {
        using var svc = NewSeamed(_ => true);
        svc.Register(HotkeyCombo.Default);
        svc.SetArmed(true);

        bool pressed = false;
        svc.Pressed += (_, _) => pressed = true;

        svc.OnHotKeyMessage(); // synthetic WM_HOTKEY

        Assert.True(pressed);
    }

    [Fact]
    public void HotKeyMessage_WhenNotArmed_DoesNotRaisePressed()
    {
        using var svc = NewSeamed(_ => true);
        svc.Register(HotkeyCombo.Default);
        // armed stays false

        bool pressed = false;
        svc.Pressed += (_, _) => pressed = true;

        svc.OnHotKeyMessage();

        Assert.False(pressed);
    }

    [Fact]
    public void ReleasePoll_AfterPress_RaisesReleasedOnceWhenKeyGoesUp()
    {
        bool keyDown = true;
        using var svc = NewSeamed(_ => keyDown);
        svc.Register(HotkeyCombo.Default);
        svc.SetArmed(true);

        int pressedCount = 0, releasedCount = 0;
        svc.Pressed += (_, _) => pressedCount++;
        svc.Released += (_, _) => releasedCount++;

        svc.OnHotKeyMessage();   // press
        svc.PollReleaseOnce();   // key still down -> no release
        Assert.Equal(0, releasedCount);

        keyDown = false;
        svc.PollReleaseOnce();   // key up -> Released

        Assert.Equal(1, pressedCount);
        Assert.Equal(1, releasedCount);

        // Further polls must not re-raise Released (edge, not level).
        svc.PollReleaseOnce();
        Assert.Equal(1, releasedCount);
    }

    [Fact]
    public void SecondPress_AfterRelease_RaisesPressedAgain()
    {
        bool keyDown = true;
        using var svc = NewSeamed(_ => keyDown);
        svc.Register(HotkeyCombo.Default);
        svc.SetArmed(true);

        int pressedCount = 0, releasedCount = 0;
        svc.Pressed += (_, _) => pressedCount++;
        svc.Released += (_, _) => releasedCount++;

        svc.OnHotKeyMessage();
        keyDown = false;
        svc.PollReleaseOnce();

        keyDown = true;
        svc.OnHotKeyMessage();
        keyDown = false;
        svc.PollReleaseOnce();

        Assert.Equal(2, pressedCount);
        Assert.Equal(2, releasedCount);
    }

    [Fact]
    public void RegisterThenUnregister_DoNotThrow_WithRealWindow()
    {
        // Real RegisterHotKey/UnregisterHotKey path (no seam): a free-threaded
        // service should register and unregister an unusual combo without
        // throwing. Uses a rarely-bound key to avoid clashing with the desktop.
        using var svc = new Win32HotkeyService();
        var combo = new HotkeyCombo(0x0001 /*MOD_ALT*/, 0x7A /*VK_F11*/);

        var ex = Record.Exception(() =>
        {
            svc.Register(combo);
            svc.Unregister();
        });

        Assert.Null(ex);
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run (Windows-side): `powershell.exe -Command "dotnet test tests/WinSuperWhisper.App.Tests --filter FullyQualifiedName~Win32HotkeyServiceTests"`
Expected: FAIL to compile - `Win32HotkeyService` does not exist.

- [ ] **Step 3: Write minimal implementation**

Create `src/WinSuperWhisper.App/Win32/Win32HotkeyService.cs`:

```csharp
using System;
using System.Windows.Threading;
using WinSuperWhisper.Core.Interfaces;
using WinSuperWhisper.Core.Models;

namespace WinSuperWhisper.App.Win32;

/// <summary>
/// Global hotkey via Win32 RegisterHotKey for the press edge (WM_HOTKEY), and
/// GetAsyncKeyState polling for the release edge - RegisterHotKey has no key-up
/// notification, and a low-level keyboard hook would be a heavier, AV-sensitive
/// mechanism than hold-to-record needs (see plan rationale).
///
/// SetArmed(false) gates BOTH edges so a hotkey press during daemon warm-up is
/// ignored. The WM_HOTKEY arrival and the release poll are seamed (internal
/// OnHotKeyMessage / PollReleaseOnce + injectable isKeyDown) so the edge logic
/// is unit-testable without a real window or keyboard.
/// </summary>
public sealed class Win32HotkeyService : IHotkeyService
{
    private const int HotkeyId = 0xB001;

    public event EventHandler? Pressed;
    public event EventHandler? Released;

    private readonly Func<int, bool> _isKeyDown;
    private readonly DispatcherTimer? _pollTimer;
    private HwndHotkeyWindow? _window;
    private HotkeyCombo? _combo;
    private bool _armed;
    private bool _holding;   // true between a raised Pressed and its Released

    /// <summary>Production constructor: real GetAsyncKeyState + a poll timer.</summary>
    public Win32HotkeyService()
        : this(DefaultIsKeyDown)
    {
        _pollTimer = new DispatcherTimer(DispatcherPriority.Input)
        {
            Interval = TimeSpan.FromMilliseconds(30),
        };
        _pollTimer.Tick += (_, _) => PollReleaseOnce();
        _pollTimer.Start();
    }

    /// <summary>Test/seam constructor: injected key-state, no timer/window.</summary>
    internal Win32HotkeyService(Func<int, bool> isKeyDown)
    {
        _isKeyDown = isKeyDown;
    }

    public bool IsArmed => _armed;

    public void SetArmed(bool armed) => _armed = armed;

    public void Register(HotkeyCombo combo)
    {
        _combo = combo;

        // Only stand up a real message-only window when we are not in the
        // seam (the seam tests drive OnHotKeyMessage directly).
        if (_pollTimer is not null)
        {
            _window ??= new HwndHotkeyWindow(OnHotKeyMessage);
            uint mods = combo.Modifiers | NativeMethods.MOD_NOREPEAT;
            if (!NativeMethods.RegisterHotKey(_window.Handle, HotkeyId, mods, combo.VirtualKey))
            {
                throw new InvalidOperationException(
                    $"RegisterHotKey failed for modifiers=0x{combo.Modifiers:X} vk=0x{combo.VirtualKey:X}");
            }
        }
    }

    public void Unregister()
    {
        if (_window is not null)
        {
            NativeMethods.UnregisterHotKey(_window.Handle, HotkeyId);
        }
        _combo = null;
    }

    /// <summary>Synthetic or real WM_HOTKEY arrival. Raises Pressed when armed.</summary>
    internal void OnHotKeyMessage()
    {
        if (!_armed || _holding)
        {
            return;
        }
        _holding = true;
        Pressed?.Invoke(this, EventArgs.Empty);
    }

    /// <summary>
    /// One release-edge check. When holding and the hotkey's virtual key reads
    /// up, raises Released exactly once. Gated by SetArmed.
    /// </summary>
    internal void PollReleaseOnce()
    {
        if (!_holding || !_armed || _combo is null)
        {
            return;
        }
        if (!_isKeyDown((int)_combo.VirtualKey))
        {
            _holding = false;
            Released?.Invoke(this, EventArgs.Empty);
        }
    }

    private static bool DefaultIsKeyDown(int vKey)
        => (NativeMethods.GetAsyncKeyState(vKey) & 0x8000) != 0;

    public void Dispose()
    {
        _pollTimer?.Stop();
        Unregister();
        _window?.Dispose();
    }
}
```

Create the message-only window helper in the same file's directory: `src/WinSuperWhisper.App/Win32/HwndHotkeyWindow.cs`:

```csharp
using System;
using System.Windows.Interop;

namespace WinSuperWhisper.App.Win32;

/// <summary>
/// A hidden HwndSource that receives WM_HOTKEY and forwards it to a callback.
/// Lives on the WPF UI thread (created during app startup), so the callback
/// runs there and event handlers can touch the UI safely.
/// </summary>
internal sealed class HwndHotkeyWindow : IDisposable
{
    private readonly HwndSource _source;
    private readonly Action _onHotKey;

    public HwndHotkeyWindow(Action onHotKey)
    {
        _onHotKey = onHotKey;
        var parameters = new HwndSourceParameters("WinSuperWhisperHotkeyWindow")
        {
            Width = 0,
            Height = 0,
            WindowStyle = 0,       // not visible
            ParentWindow = new IntPtr(-3), // HWND_MESSAGE: message-only window
        };
        _source = new HwndSource(parameters);
        _source.AddHook(WndProc);
    }

    public IntPtr Handle => _source.Handle;

    private IntPtr WndProc(IntPtr hwnd, int msg, IntPtr wParam, IntPtr lParam, ref bool handled)
    {
        if (msg == NativeMethods.WM_HOTKEY)
        {
            _onHotKey();
            handled = true;
        }
        return IntPtr.Zero;
    }

    public void Dispose() => _source.Dispose();
}
```

- [ ] **Step 4: Run test to verify it passes**

Run (Windows-side): `powershell.exe -Command "dotnet test tests/WinSuperWhisper.App.Tests --filter FullyQualifiedName~Win32HotkeyServiceTests"`
Expected: PASS - 7 passed. (`RegisterThenUnregister_DoNotThrow_WithRealWindow` exercises the real `RegisterHotKey` path on an STA test thread; if the chosen combo is already taken by the desktop, the registration throws and the test fails loudly - that is a real conflict to escalate, not a flaky test.)

> **Note on the real-window test and STA:** WPF `HwndSource` requires an STA thread. If `dotnet test` runs the fact on an MTA thread and `HwndSource` construction throws, that is an infrastructure detail, not an adapter bug: add `[assembly: System.Runtime.Versioning.SupportedOSPlatform("windows")]` is already implied by the TFM, and annotate the real-window fact's class or the test with an STA runner only if needed. If you cannot make the real-window fact run STA without redesign, STOP and escalate rather than deleting it - this is a judgment call.

- [ ] **Step 5: Commit**

```bash
git add src/WinSuperWhisper.App/Win32/Win32HotkeyService.cs \
        src/WinSuperWhisper.App/Win32/HwndHotkeyWindow.cs \
        tests/WinSuperWhisper.App.Tests/Win32HotkeyServiceTests.cs
git commit -m "feat: Win32HotkeyService with RegisterHotKey + GetAsyncKeyState release polling"
```

---

### Task 6: Full Windows-tier run + manual-verification checklist

**Files:** none (verification task).

- [ ] **Step 1: Run the entire Windows adapter tier the way the gate does**

From WSL:
`powershell.exe -File scripts/win-tests.ps1`

Expected (streamed from PowerShell into the WSL terminal):

```
Passed!  - Failed:     0, Passed:    21, Skipped:     2, Total:    23, Duration: ...
```

(21 deterministic adapter facts passing, 2 documented manual facts skipped - the real-UIPI injection and the real-microphone capture. Counts are approximate if `04-ui`/`05-movein` tests are not yet present; the binding requirement is Failed: 0 with no silent skips beyond the two documented manual ones.)

- [ ] **Step 2: Record the manual-verification steps as performed (or escalate if blocked)**

These two checks cannot be made deterministic in a unit test. Perform them once on the real Windows 11 machine and note the result; if you cannot (e.g. no admin rights for the elevated-window check, or no microphone), record that and escalate rather than marking them done:

1. **UIPI -> clipboard fallback (manual):** run WinSuperWhisper non-elevated; focus an elevated (Run as administrator) terminal; trigger an injection; confirm the transcript arrives via Ctrl+V (the `ClipboardFallback` path) and that the app did NOT elevate itself.
2. **Real microphone capture (manual):** on a machine with a mic, run the skipped `RealDevice_CapturesSixteenKMonoPcm_MANUAL` fact (remove the `Skip` locally, do not commit that removal) and confirm it yields >8000 bytes of 16 kHz mono 16-bit PCM.

- [ ] **Step 3: Commit (verification note only if any plan doc changed; otherwise nothing to commit)**

No code changes in this task. If you added nothing, there is nothing to commit; the gate-green run is the deliverable.

---

## Self-review (performed against the contract and spec)

- **Interface conformance:** `Win32HotkeyService` implements `IHotkeyService` (`Pressed`, `Released`, `Register`, `Unregister`, `IsArmed`, `SetArmed`, `IDisposable`). `NAudioCapture` implements `IAudioCapture` (`LevelAvailable`, `Start`, `Stop`, `GetCapturedPcm`, `IsCapturing`, `IDisposable`). `Win32TextInjector` implements `ITextInjector` (`Inject` -> `InjectionResult`). `Win32MonitorService` implements `IMonitorService` (`GetMonitors`, `FindById`). All names/signatures match the contract verbatim.
- **Model conformance:** `MonitorInfo` is constructed with the exact positional record shape (Id, Name, WidthPx, HeightPx, DpiScale, WorkAreaLeft, WorkAreaTop, WorkAreaRight, WorkAreaBottom, IsPrimary). `AudioLevel(float Peak)` normalized 0..1. `InjectionResult` values `Typed`/`ClipboardFallback`/`Failed` all returned.
- **Spec behaviors covered:** hold-to-record press/release (Data Flow steps 1-2), 16 kHz mono PCM (Architecture, NAudio), SendInput-0 -> clipboard fallback without auto-elevation (Failure Paths > UIPI), DPI-aware monitor work area for overlay positioning (UI Design + IMonitorService).
- **No placeholders:** every step has complete code and exact commands.

---

## Exit conditions (all must be green)

- [ ] `WinSuperWhisper.App` builds on Windows with NAudio referenced and `InternalsVisibleTo WinSuperWhisper.App.Tests` (Task 0).
- [ ] `tests/WinSuperWhisper.App.Tests` Win32 + NAudio adapter tests are **green on Windows 11** via `powershell.exe -File scripts/win-tests.ps1` - Failed: 0.
- [ ] **SendInput-0 -> clipboard fallback is proven** by a forced 0-return in `Win32TextInjectorTests` (`Inject_WhenSendInputReturnsZero_FallsBackToClipboardAndReturnsClipboardFallback` returns `ClipboardFallback` and sets the clipboard); the genuine elevated-window UIPI case is a documented, visible Skipped manual fact, not a silent skip.
- [ ] **Mic capture yields 16 kHz mono 16-bit little-endian PCM**: deterministic buffering/format/level facts pass; the real-device capture is a documented, visible Skipped manual fact verified once on a mic-equipped machine.
- [ ] `Win32MonitorService` returns at least one monitor with a sane `DpiScale` (0.5..4.0), a non-empty work area, and exactly one primary.
- [ ] `Win32HotkeyService` Register/Unregister do not throw, and `SetArmed(false)` gates both Pressed and Released.
- [ ] No test was weakened, silently skipped, or deleted; any non-deterministic behavior is an explicit `[Fact(Skip=...)]` manual-verification step.
- [ ] The Podman tier did NOT attempt to run this file (by design - `net8.0-windows` + Win32 + NAudio); `FM_SKIP_WIN=1` skips it loudly.

**Depends on:** `02a-core` (the interfaces and models implemented here) and `01-foundation` (the App project + `scripts/win-tests.ps1`).
**Unlocks:** `04-ui` (overlay consumes `IMonitorService` DPI/work area, `IAudioCapture.LevelAvailable`, and the hotkey press/release edges).
