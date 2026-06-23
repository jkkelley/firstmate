# WinSuperWhisper Phase 1 - Move-in / Commissioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire all real adapters and the daemon together into a working app: launch the WSL whisper daemon asynchronously (never hanging the WPF UI thread), gate the hotkey until the daemon reports `READY`, run the full hold→speak→type pipeline end-to-end on Windows 11, and prove a clean `[EXIT]` shutdown that leaves no zombie process.

**Architecture:** `DaemonProcessManager` launches `wsl.exe` via a non-blocking `Process.Start` (`UseShellExecute=false`, redirected stdout/stderr, **never** `WaitForExit` on the UI thread) and owns the process handle for monitoring/kill. A pure `WslPath.UncToLinux` converts the configured `\\wsl$` UNC model/script paths into Linux paths for the daemon arguments — unit-tested in Podman. The startup sequence (load config → launch daemon → connect → await `READY` → arm hotkey) is encoded in a small seam-injected `StartupSequencer` so its ordering is unit-testable with mocks, then `App.xaml.cs` composes the real adapters and drives it. Focus capture/restore uses plain `GetForegroundWindow`/`SetForegroundWindow` in Phase 1; the `AttachThreadInput` hardening is explicitly DEFERRED to Phase 4.

**Tech Stack:** .NET 8 (`net8.0` Core, `net8.0-windows` App), WPF, NAudio, Win32 P/Invoke, xUnit + Moq, Python whisper daemon in WSL, Podman (Linux test tier), `powershell.exe` (Windows test tier).

**Spec:** `/home/luna/projects/firstmate/docs/superpowers/specs/2026-06-22-winsuperwhisper-design.md` (read Data Flow > Startup and Failure Paths before starting).

**Standalone repo:** This plan targets the standalone `WinSuperWhisper` git repo (default branch `main`). It does NOT live under firstmate; reference the spec only by the absolute path above.

---

## Escalation contract (read first)

- **Exit conditions are binary.** Every item in "Exit conditions (all must be green)" at the end is pass/fail. There is no partial credit.
- **Mechanical failures get a bounded 2-attempt retry.** A flaky build, a transient `dotnet restore` network blip, a tmux/powershell hiccup: retry at most twice, then escalate with evidence.
- **Any judgment call stops and escalates immediately.** Specifically:
  - The daemon launch hangs the WPF UI (app window unresponsive during warm-up) — this is the single most likely failure of this whole plan; if it happens, STOP and escalate with the offending `Process.Start`/await code.
  - A zombie `python3 whisper_daemon.py` survives app exit (the no-zombie check below fails).
  - Focus restore is unreliable (transcript types into the wrong window). Phase 1 ships plain capture/restore and documents the limitation; do **not** improvise the `AttachThreadInput` hardening here — that is Phase 4. Escalate instead.
  - Any ambiguous spec detail, a needed credential, or the unavailability of the Win11 machine.
  - Any temptation to weaken a test to make it pass.
- **Dependencies.** This file is the capstone of Phase 1. It depends on `03-adapters` (Win32HotkeyService, NAudioCapture, Win32TextInjector, Win32MonitorService) and `04-ui` (OverlayWindow, SettingsWindow, TrayIcon) being merged. It ships LAST in the Phase 1 PR set.
- **PODMAN vs WIN11 tagging.** Each task is tagged. PODMAN tasks (pure path conversion, mocked startup/shutdown ordering) are fully verifiable here on Linux. WIN11 tasks (real `wsl.exe` launch, no-hang assertion, no-zombie check, speak→type e2e) require the Windows machine via `powershell.exe` and are partly manual — each WIN11 task states honestly what is automated and what is a manual checklist.

---

## Task 1 (PODMAN): `WslPath.UncToLinux` — pure UNC→Linux path conversion

The daemon needs a Linux path (`/home/...`, `/mnt/...`) but config stores Windows UNC paths (`\\wsl$\Ubuntu\...` or `\\wsl.localhost\Ubuntu\...`). This conversion is pure and must be unit-tested in Podman. It lives in Core so it has no Windows dependency.

**Files:**

- Create: `src/WinSuperWhisper.Core/Daemon/WslPath.cs`
- Test: `tests/WinSuperWhisper.Tests/Daemon/WslPathTests.cs`

- [ ] **Step 1: Write the failing test**

```csharp
// tests/WinSuperWhisper.Tests/Daemon/WslPathTests.cs
using WinSuperWhisper.Core.Daemon;
using Xunit;

namespace WinSuperWhisper.Tests.Daemon;

public class WslPathTests
{
    [Fact]
    public void Converts_wsl_dollar_unc_to_linux_path()
    {
        var linux = WslPath.UncToLinux(@"\\wsl$\Ubuntu\home\luna\models\base", out var distro);
        Assert.Equal("Ubuntu", distro);
        Assert.Equal("/home/luna/models/base", linux);
    }

    [Fact]
    public void Converts_wsl_localhost_unc_to_linux_path()
    {
        var linux = WslPath.UncToLinux(@"\\wsl.localhost\Ubuntu-22.04\opt\whisper\daemon.py", out var distro);
        Assert.Equal("Ubuntu-22.04", distro);
        Assert.Equal("/opt/whisper/daemon.py", linux);
    }

    [Fact]
    public void Handles_forward_slashes_in_unc()
    {
        var linux = WslPath.UncToLinux("//wsl$/Ubuntu/home/luna/m", out var distro);
        Assert.Equal("Ubuntu", distro);
        Assert.Equal("/home/luna/m", linux);
    }

    [Fact]
    public void Root_of_distro_maps_to_slash()
    {
        var linux = WslPath.UncToLinux(@"\\wsl$\Ubuntu", out var distro);
        Assert.Equal("Ubuntu", distro);
        Assert.Equal("/", linux);
    }

    [Fact]
    public void Trailing_separator_is_trimmed()
    {
        var linux = WslPath.UncToLinux(@"\\wsl$\Ubuntu\home\luna\model\", out var distro);
        Assert.Equal("Ubuntu", distro);
        Assert.Equal("/home/luna/model", linux);
    }

    [Theory]
    [InlineData("")]
    [InlineData(@"C:\Users\luna\model")]
    [InlineData(@"\\server\share\path")]
    public void Rejects_non_wsl_unc(string bad)
    {
        Assert.Throws<System.ArgumentException>(() => WslPath.UncToLinux(bad, out _));
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `dotnet test tests/WinSuperWhisper.Tests --filter "FullyQualifiedName~WslPathTests"`
Expected: FAIL — `WslPath` does not exist (compile error / type not found).

- [ ] **Step 3: Write minimal implementation**

```csharp
// src/WinSuperWhisper.Core/Daemon/WslPath.cs
using System;

namespace WinSuperWhisper.Core.Daemon;

/// <summary>
/// Pure conversion of a Windows WSL UNC path (\\wsl$\Distro\... or \\wsl.localhost\Distro\...)
/// into the Linux-side path the daemon needs, plus the distro name. No Windows dependency:
/// this lives in Core so it is unit-testable in Podman.
/// </summary>
public static class WslPath
{
    public static string UncToLinux(string unc, out string distro)
    {
        if (string.IsNullOrWhiteSpace(unc))
            throw new ArgumentException("UNC path is empty.", nameof(unc));

        // Normalize separators to '/'.
        var normalized = unc.Replace('\\', '/');

        // Strip a single leading "//" (the UNC prefix), tolerating already-stripped input.
        string body;
        if (normalized.StartsWith("//", StringComparison.Ordinal))
            body = normalized.Substring(2);
        else
            throw new ArgumentException($"Not a UNC path: '{unc}'.", nameof(unc));

        // Expect "wsl$/<distro>/..." or "wsl.localhost/<distro>/...".
        var parts = body.Split('/', StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length < 2)
            throw new ArgumentException($"Not a WSL UNC path: '{unc}'.", nameof(unc));

        var host = parts[0];
        if (!host.Equals("wsl$", StringComparison.OrdinalIgnoreCase) &&
            !host.Equals("wsl.localhost", StringComparison.OrdinalIgnoreCase))
            throw new ArgumentException($"Not a WSL host ('{host}'): '{unc}'.", nameof(unc));

        distro = parts[1];

        if (parts.Length == 2)
            return "/";

        // Everything after host + distro is the Linux path.
        var rest = string.Join('/', parts, 2, parts.Length - 2);
        return "/" + rest;
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `dotnet test tests/WinSuperWhisper.Tests --filter "FullyQualifiedName~WslPathTests"`
Expected: PASS (all 9 cases).

- [ ] **Step 5: Commit**

```bash
git add src/WinSuperWhisper.Core/Daemon/WslPath.cs tests/WinSuperWhisper.Tests/Daemon/WslPathTests.cs
git commit -m "feat(daemon): pure WSL UNC->Linux path conversion"
```

---

## Task 2 (PODMAN): Daemon launch-spec builder — pure argument assembly

Before building the real process launcher (which needs Windows), extract the _argument assembly_ into a pure, testable function in Core. This is what the WIN11 `DaemonProcessManager` will consume. It uses `WslPath` from Task 1 and `AppConfig` to produce the exact `wsl.exe` argument list the spec mandates.

**Files:**

- Create: `src/WinSuperWhisper.Core/Daemon/DaemonLaunchSpec.cs`
- Test: `tests/WinSuperWhisper.Tests/Daemon/DaemonLaunchSpecTests.cs`

- [ ] **Step 1: Write the failing test**

```csharp
// tests/WinSuperWhisper.Tests/Daemon/DaemonLaunchSpecTests.cs
using WinSuperWhisper.Core.Daemon;
using WinSuperWhisper.Core.Models;
using Xunit;

namespace WinSuperWhisper.Tests.Daemon;

public class DaemonLaunchSpecTests
{
    private static AppConfig Config() => new()
    {
        Distro = "Ubuntu",
        DaemonScriptPathUnc = @"\\wsl$\Ubuntu\opt\whisper\whisper_daemon.py",
        ModelPathUnc = @"\\wsl$\Ubuntu\home\luna\models\base",
        Language = "auto",
    };

    [Fact]
    public void Builds_wsl_exe_filename()
    {
        var spec = DaemonLaunchSpec.From(Config(), port: 8765);
        Assert.Equal("wsl.exe", spec.FileName);
    }

    [Fact]
    public void Builds_expected_argument_sequence()
    {
        var spec = DaemonLaunchSpec.From(Config(), port: 8765);
        Assert.Equal(new[]
        {
            "-d", "Ubuntu",
            "-e", "python3",
            "/opt/whisper/whisper_daemon.py",
            "--model", "/home/luna/models/base",
            "--host", "0.0.0.0",
            "--port", "8765",
            "--language", "auto",
        }, spec.Arguments);
    }

    [Fact]
    public void Uses_distro_from_script_unc_when_present()
    {
        // The script UNC carries the authoritative distro; it must agree with config.Distro.
        var cfg = Config();
        cfg.DaemonScriptPathUnc = @"\\wsl.localhost\Ubuntu\opt\whisper\whisper_daemon.py";
        var spec = DaemonLaunchSpec.From(cfg, port: 8765);
        Assert.Equal("Ubuntu", spec.Arguments[1]);
    }

    [Fact]
    public void Throws_when_script_path_missing()
    {
        var cfg = Config();
        cfg.DaemonScriptPathUnc = "";
        Assert.Throws<System.ArgumentException>(() => DaemonLaunchSpec.From(cfg, port: 8765));
    }

    [Fact]
    public void Throws_when_model_path_missing()
    {
        var cfg = Config();
        cfg.ModelPathUnc = "";
        Assert.Throws<System.ArgumentException>(() => DaemonLaunchSpec.From(cfg, port: 8765));
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `dotnet test tests/WinSuperWhisper.Tests --filter "FullyQualifiedName~DaemonLaunchSpecTests"`
Expected: FAIL — `DaemonLaunchSpec` does not exist.

- [ ] **Step 3: Write minimal implementation**

```csharp
// src/WinSuperWhisper.Core/Daemon/DaemonLaunchSpec.cs
using System;
using System.Collections.Generic;
using WinSuperWhisper.Core.Models;

namespace WinSuperWhisper.Core.Daemon;

/// <summary>
/// Pure assembly of the wsl.exe launch command for the whisper daemon. Produced in Core so the
/// exact argument list is unit-testable in Podman; the WIN11 DaemonProcessManager consumes it to
/// configure ProcessStartInfo. The launch is:
///   wsl.exe -d &lt;distro&gt; -e python3 &lt;linux-script&gt; --model &lt;linux-model-dir&gt;
///           --host 0.0.0.0 --port &lt;port&gt; --language &lt;lang&gt;
/// </summary>
public sealed record DaemonLaunchSpec(string FileName, IReadOnlyList<string> Arguments)
{
    public static DaemonLaunchSpec From(AppConfig config, int port)
    {
        if (string.IsNullOrWhiteSpace(config.DaemonScriptPathUnc))
            throw new ArgumentException("DaemonScriptPathUnc is not configured.", nameof(config));
        if (string.IsNullOrWhiteSpace(config.ModelPathUnc))
            throw new ArgumentException("ModelPathUnc is not configured.", nameof(config));

        var scriptLinux = WslPath.UncToLinux(config.DaemonScriptPathUnc, out var distro);
        var modelLinux = WslPath.UncToLinux(config.ModelPathUnc, out _);

        var args = new List<string>
        {
            "-d", distro,
            "-e", "python3",
            scriptLinux,
            "--model", modelLinux,
            "--host", "0.0.0.0",
            "--port", port.ToString(System.Globalization.CultureInfo.InvariantCulture),
            "--language", string.IsNullOrWhiteSpace(config.Language) ? "auto" : config.Language,
        };

        return new DaemonLaunchSpec("wsl.exe", args);
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `dotnet test tests/WinSuperWhisper.Tests --filter "FullyQualifiedName~DaemonLaunchSpecTests"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/WinSuperWhisper.Core/Daemon/DaemonLaunchSpec.cs tests/WinSuperWhisper.Tests/Daemon/DaemonLaunchSpecTests.cs
git commit -m "feat(daemon): pure wsl.exe launch-spec builder"
```

---

## Task 3 (PODMAN): `IDaemonProcess` seam + `StartupSequencer` ordering

The startup ordering (per spec Data Flow > Startup) is business logic and must be unit-testable in Podman, so it lives in Core behind a process seam. We define a tiny `IDaemonProcess` interface (the only thing `DaemonProcessManager` will implement that the sequencer needs) plus `StartupSequencer`, which encodes the exact order: **launch daemon → connect+await READY → arm hotkey**. The hotkey must stay gated (`SetArmed(false)` / never `SetArmed(true)`) until `READY`.

**Files:**

- Create: `src/WinSuperWhisper.Core/Daemon/IDaemonProcess.cs`
- Create: `src/WinSuperWhisper.Core/Orchestrator/StartupSequencer.cs`
- Test: `tests/WinSuperWhisper.Tests/Orchestrator/StartupSequencerTests.cs`

- [ ] **Step 1: Write the failing test**

```csharp
// tests/WinSuperWhisper.Tests/Orchestrator/StartupSequencerTests.cs
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using Moq;
using WinSuperWhisper.Core.Daemon;
using WinSuperWhisper.Core.Interfaces;
using WinSuperWhisper.Core.Models;
using WinSuperWhisper.Core.Orchestrator;
using Xunit;

namespace WinSuperWhisper.Tests.Orchestrator;

public class StartupSequencerTests
{
    private static AppConfig Config() => new()
    {
        Distro = "Ubuntu",
        DaemonScriptPathUnc = @"\\wsl$\Ubuntu\opt\whisper\whisper_daemon.py",
        ModelPathUnc = @"\\wsl$\Ubuntu\home\luna\models\base",
        Hotkey = HotkeyCombo.Default,
    };

    [Fact]
    public async Task Launches_daemon_before_connecting()
    {
        var order = new List<string>();
        var process = new Mock<IDaemonProcess>();
        var client = new Mock<IDaemonClient>();
        var hotkey = new Mock<IHotkeyService>();

        process.Setup(p => p.Launch(It.IsAny<AppConfig>())).Callback(() => order.Add("launch"));
        client.Setup(c => c.ConnectAsync(It.IsAny<CancellationToken>()))
              .Returns(Task.CompletedTask).Callback(() => order.Add("connect"));

        var seq = new StartupSequencer(process.Object, client.Object, hotkey.Object);
        await seq.RunAsync(Config(), CancellationToken.None);

        Assert.Equal(new[] { "launch", "connect" }, order.ToArray());
    }

    [Fact]
    public async Task Arms_hotkey_only_after_ready()
    {
        var order = new List<string>();
        var process = new Mock<IDaemonProcess>();
        var client = new Mock<IDaemonClient>();
        var hotkey = new Mock<IHotkeyService>();

        // ConnectAsync resolves only once READY has been observed by the client.
        client.Setup(c => c.ConnectAsync(It.IsAny<CancellationToken>()))
              .Returns(Task.CompletedTask).Callback(() => order.Add("connect-ready"));
        hotkey.Setup(h => h.Register(It.IsAny<HotkeyCombo>())).Callback(() => order.Add("register"));
        hotkey.Setup(h => h.SetArmed(true)).Callback(() => order.Add("arm"));

        var seq = new StartupSequencer(process.Object, client.Object, hotkey.Object);
        await seq.RunAsync(Config(), CancellationToken.None);

        // Register may happen anytime, but SetArmed(true) must come strictly after connect-ready.
        var connectIdx = order.IndexOf("connect-ready");
        var armIdx = order.IndexOf("arm");
        Assert.True(connectIdx >= 0 && armIdx >= 0);
        Assert.True(armIdx > connectIdx, "hotkey armed before READY");
    }

    [Fact]
    public async Task Hotkey_starts_gated()
    {
        var process = new Mock<IDaemonProcess>();
        var client = new Mock<IDaemonClient>();
        var hotkey = new Mock<IHotkeyService>();
        client.Setup(c => c.ConnectAsync(It.IsAny<CancellationToken>())).Returns(Task.CompletedTask);

        var seq = new StartupSequencer(process.Object, client.Object, hotkey.Object);
        await seq.RunAsync(Config(), CancellationToken.None);

        // Gated first (false), then armed (true) once. Never armed before being gated.
        hotkey.Verify(h => h.SetArmed(false), Times.AtLeastOnce);
        hotkey.Verify(h => h.SetArmed(true), Times.Once);
    }

    [Fact]
    public async Task On_connect_failure_retries_once_after_relaunch()
    {
        var process = new Mock<IDaemonProcess>();
        var client = new Mock<IDaemonClient>();
        var hotkey = new Mock<IHotkeyService>();

        var calls = 0;
        client.Setup(c => c.ConnectAsync(It.IsAny<CancellationToken>()))
              .Returns(() =>
              {
                  calls++;
                  if (calls == 1) throw new System.IO.IOException("connection refused");
                  return Task.CompletedTask;
              });

        var seq = new StartupSequencer(process.Object, client.Object, hotkey.Object);
        await seq.RunAsync(Config(), CancellationToken.None);

        // Spec Failure Paths: daemon not running -> auto-restart + retry once.
        process.Verify(p => p.Launch(It.IsAny<AppConfig>()), Times.Exactly(2));
        client.Verify(c => c.ConnectAsync(It.IsAny<CancellationToken>()), Times.Exactly(2));
        hotkey.Verify(h => h.SetArmed(true), Times.Once);
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `dotnet test tests/WinSuperWhisper.Tests --filter "FullyQualifiedName~StartupSequencerTests"`
Expected: FAIL — `IDaemonProcess` / `StartupSequencer` do not exist.

- [ ] **Step 3: Write minimal implementation**

```csharp
// src/WinSuperWhisper.Core/Daemon/IDaemonProcess.cs
using System;
using WinSuperWhisper.Core.Models;

namespace WinSuperWhisper.Core.Daemon;

/// <summary>
/// The process-lifecycle seam the startup logic depends on. Implemented on Windows by
/// DaemonProcessManager (which owns the real wsl.exe handle). Kept in Core so StartupSequencer
/// is unit-testable in Podman with a mock.
/// </summary>
public interface IDaemonProcess : IDisposable
{
    /// <summary>Launch the daemon asynchronously (non-blocking). Never waits for the process to exit.</summary>
    void Launch(AppConfig config);

    /// <summary>True while the launched process is alive.</summary>
    bool IsRunning { get; }

    /// <summary>Ensure the process is gone (kill if necessary). Idempotent.</summary>
    void Stop();
}
```

```csharp
// src/WinSuperWhisper.Core/Orchestrator/StartupSequencer.cs
using System.Threading;
using System.Threading.Tasks;
using WinSuperWhisper.Core.Daemon;
using WinSuperWhisper.Core.Interfaces;
using WinSuperWhisper.Core.Models;

namespace WinSuperWhisper.Core.Orchestrator;

/// <summary>
/// Encodes the startup ordering from the design spec (Data Flow > Startup):
///   1. launch daemon (async, non-blocking)
///   2. open persistent connection and await READY
///   3. register hotkey, then arm it ONLY after READY
/// The hotkey is held gated (SetArmed(false)) until the daemon is READY so a press during model
/// load cannot produce a failed transcription. On a connect failure (daemon not up) it relaunches
/// and retries exactly once, per Failure Paths.
/// </summary>
public sealed class StartupSequencer
{
    private readonly IDaemonProcess _process;
    private readonly IDaemonClient _client;
    private readonly IHotkeyService _hotkey;

    public StartupSequencer(IDaemonProcess process, IDaemonClient client, IHotkeyService hotkey)
    {
        _process = process;
        _client = client;
        _hotkey = hotkey;
    }

    public async Task RunAsync(AppConfig config, CancellationToken ct)
    {
        // Hotkey is registered but gated: it cannot fire a transcription until READY.
        _hotkey.SetArmed(false);
        _hotkey.Register(config.Hotkey);

        // 1. Launch daemon (non-blocking) and 2. connect+await READY, with a single relaunch+retry.
        _process.Launch(config);
        try
        {
            await _client.ConnectAsync(ct).ConfigureAwait(false);
        }
        catch (System.Exception) when (!ct.IsCancellationRequested)
        {
            // Daemon not running / connection refused: auto-restart and retry once.
            _process.Stop();
            _process.Launch(config);
            await _client.ConnectAsync(ct).ConfigureAwait(false);
        }

        // 3. READY observed (ConnectAsync resolved): arm the hotkey.
        _hotkey.SetArmed(true);
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `dotnet test tests/WinSuperWhisper.Tests --filter "FullyQualifiedName~StartupSequencerTests"`
Expected: PASS (all 4 cases).

- [ ] **Step 5: Commit**

```bash
git add src/WinSuperWhisper.Core/Daemon/IDaemonProcess.cs src/WinSuperWhisper.Core/Orchestrator/StartupSequencer.cs tests/WinSuperWhisper.Tests/Orchestrator/StartupSequencerTests.cs
git commit -m "feat(orchestrator): seam-injected startup sequencer with READY gate and retry-once"
```

---

## Task 4 (PODMAN): Shutdown ordering — `[EXIT]` then process stop

Shutdown must send `[EXIT]` via the daemon client _before_ killing the process, so the daemon exits cleanly on its own (the process `Stop` is only the no-zombie backstop). Encode this ordering behind the same seams and test it with mocks in Podman.

**Files:**

- Create: `src/WinSuperWhisper.Core/Orchestrator/ShutdownSequencer.cs`
- Test: `tests/WinSuperWhisper.Tests/Orchestrator/ShutdownSequencerTests.cs`

- [ ] **Step 1: Write the failing test**

```csharp
// tests/WinSuperWhisper.Tests/Orchestrator/ShutdownSequencerTests.cs
using System.Collections.Generic;
using System.Threading.Tasks;
using Moq;
using WinSuperWhisper.Core.Daemon;
using WinSuperWhisper.Core.Interfaces;
using WinSuperWhisper.Core.Orchestrator;
using Xunit;

namespace WinSuperWhisper.Tests.Orchestrator;

public class ShutdownSequencerTests
{
    [Fact]
    public async Task Sends_exit_before_stopping_process()
    {
        var order = new List<string>();
        var client = new Mock<IDaemonClient>();
        var process = new Mock<IDaemonProcess>();

        client.Setup(c => c.ShutdownAsync()).Returns(Task.CompletedTask).Callback(() => order.Add("exit"));
        process.Setup(p => p.Stop()).Callback(() => order.Add("stop"));

        var seq = new ShutdownSequencer(client.Object, process.Object);
        await seq.RunAsync();

        Assert.Equal(new[] { "exit", "stop" }, order.ToArray());
    }

    [Fact]
    public async Task Still_stops_process_if_exit_throws()
    {
        var client = new Mock<IDaemonClient>();
        var process = new Mock<IDaemonProcess>();

        client.Setup(c => c.ShutdownAsync()).ThrowsAsync(new System.IO.IOException("socket gone"));

        var seq = new ShutdownSequencer(client.Object, process.Object);
        await seq.RunAsync();   // must not throw

        // No-zombie guarantee: process is stopped even when the graceful [EXIT] fails.
        process.Verify(p => p.Stop(), Times.Once);
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `dotnet test tests/WinSuperWhisper.Tests --filter "FullyQualifiedName~ShutdownSequencerTests"`
Expected: FAIL — `ShutdownSequencer` does not exist.

- [ ] **Step 3: Write minimal implementation**

```csharp
// src/WinSuperWhisper.Core/Orchestrator/ShutdownSequencer.cs
using System.Threading.Tasks;
using WinSuperWhisper.Core.Daemon;
using WinSuperWhisper.Core.Interfaces;

namespace WinSuperWhisper.Core.Orchestrator;

/// <summary>
/// Clean shutdown: send [EXIT] over the persistent connection so the daemon's serve loop exits
/// on its own, THEN ensure the process is gone as a no-zombie backstop. The process is always
/// stopped, even if the graceful [EXIT] fails (e.g. socket already dead).
/// </summary>
public sealed class ShutdownSequencer
{
    private readonly IDaemonClient _client;
    private readonly IDaemonProcess _process;

    public ShutdownSequencer(IDaemonClient client, IDaemonProcess process)
    {
        _client = client;
        _process = process;
    }

    public async Task RunAsync()
    {
        try
        {
            await _client.ShutdownAsync().ConfigureAwait(false);
        }
        catch
        {
            // Graceful exit failed; the backstop below still guarantees no zombie.
        }
        finally
        {
            _process.Stop();
        }
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `dotnet test tests/WinSuperWhisper.Tests --filter "FullyQualifiedName~ShutdownSequencerTests"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/WinSuperWhisper.Core/Orchestrator/ShutdownSequencer.cs tests/WinSuperWhisper.Tests/Orchestrator/ShutdownSequencerTests.cs
git commit -m "feat(orchestrator): shutdown sends [EXIT] then stops process (no zombie)"
```

---

## Task 5 (WIN11): `DaemonProcessManager` — real async wsl.exe launch

This is the real Windows process manager. **THE LOAD-BEARING DETAIL:** the launch is asynchronous and non-blocking. The daemon is a persistent server, so it never exits on its own while running — `WaitForExit` would block forever. Use `Process.Start` with `UseShellExecute=false` and redirected stdout/stderr, and **NEVER** call `WaitForExit` on the UI thread. Output is drained on background threads via `BeginOutputReadLine`/`BeginErrorReadLine`. The class implements `IDaemonProcess` (from Task 3) and holds the handle for monitor + kill on app exit.

Because this is a real-process class, its `.App.Tests` assertions run only on Windows. The pure argument building is already covered by Task 2 in Podman; here the Windows test asserts the no-hang behavior and process liveness.

**Files:**

- Create: `src/WinSuperWhisper.App/Win32/DaemonProcessManager.cs`
- Test: `tests/WinSuperWhisper.App.Tests/Win32/DaemonProcessManagerTests.cs`

- [ ] **Step 1: Write the failing test (WIN11)**

```csharp
// tests/WinSuperWhisper.App.Tests/Win32/DaemonProcessManagerTests.cs
using System.Diagnostics;
using WinSuperWhisper.App.Win32;
using WinSuperWhisper.Core.Models;
using Xunit;

namespace WinSuperWhisper.App.Tests.Win32;

public class DaemonProcessManagerTests
{
    // Launch a harmless long-running WSL command (sleep) instead of the real daemon, so this test
    // verifies the LAUNCH MECHANICS (non-blocking, handle captured, kill works) without needing a
    // model. The real-model launch is exercised by the e2e checklist in Task 8.
    private static AppConfig SleepConfig() => new()
    {
        Distro = "Ubuntu",
        // Point the "script" at a real path so UncToLinux succeeds; we override the launch below.
        DaemonScriptPathUnc = @"\\wsl$\Ubuntu\bin\true",
        ModelPathUnc = @"\\wsl$\Ubuntu\tmp",
        Language = "auto",
    };

    [Fact]
    public void Launch_returns_immediately_and_does_not_block()
    {
        using var mgr = new DaemonProcessManager(port: 8765);
        var sw = Stopwatch.StartNew();

        // LaunchRaw lets the test launch `sleep 30` via wsl.exe to model a persistent server that
        // never exits on its own. The call MUST return well under the sleep duration.
        mgr.LaunchRaw("wsl.exe", new[] { "-d", "Ubuntu", "-e", "sleep", "30" });
        sw.Stop();

        Assert.True(sw.ElapsedMilliseconds < 5000,
            $"Launch blocked for {sw.ElapsedMilliseconds}ms - it must be non-blocking (no WaitForExit).");
        Assert.True(mgr.IsRunning, "process handle not captured / process not alive after launch");

        mgr.Stop();
        Assert.False(mgr.IsRunning, "process still alive after Stop()");
    }

    [Fact]
    public void Stop_is_idempotent_and_kills_handle()
    {
        using var mgr = new DaemonProcessManager(port: 8765);
        mgr.LaunchRaw("wsl.exe", new[] { "-d", "Ubuntu", "-e", "sleep", "30" });
        mgr.Stop();
        mgr.Stop();   // second call must not throw
        Assert.False(mgr.IsRunning);
    }

    [Fact]
    public void Launch_uses_launch_spec_from_config()
    {
        using var mgr = new DaemonProcessManager(port: 8765);
        // Launch from config goes through DaemonLaunchSpec; bin/true exits 0 immediately, which is
        // fine here - we only assert the call returns without throwing and without blocking.
        var sw = Stopwatch.StartNew();
        mgr.Launch(SleepConfig());
        sw.Stop();
        Assert.True(sw.ElapsedMilliseconds < 5000);
        mgr.Stop();
    }
}
```

- [ ] **Step 2: Run test to verify it fails (WIN11)**

Run: `powershell.exe -File scripts/win-tests.ps1`
Expected: FAIL — `DaemonProcessManager` does not exist (compile error in `.App.Tests`).

- [ ] **Step 3: Write the implementation**

```csharp
// src/WinSuperWhisper.App/Win32/DaemonProcessManager.cs
using System;
using System.Collections.Generic;
using System.Diagnostics;
using WinSuperWhisper.Core.Daemon;
using WinSuperWhisper.Core.Models;

namespace WinSuperWhisper.App.Win32;

/// <summary>
/// Owns the WSL whisper-daemon process. THE LOAD-BEARING DETAIL: the launch is asynchronous and
/// NON-BLOCKING. The daemon is a persistent TCP server that never exits on its own while running,
/// so we must NEVER call WaitForExit on (or off) the UI thread - that would hang the WPF app
/// forever at startup. We use Process.Start with UseShellExecute=false and redirected output,
/// drain stdout/stderr on background threads, and keep the handle only for monitoring and kill.
/// </summary>
public sealed class DaemonProcessManager : IDaemonProcess
{
    private readonly int _port;
    private readonly object _gate = new();
    private Process? _process;
    private bool _disposed;

    public DaemonProcessManager(int port)
    {
        _port = port;
    }

    public bool IsRunning
    {
        get
        {
            lock (_gate)
            {
                try { return _process is { HasExited: false }; }
                catch { return false; }
            }
        }
    }

    /// <summary>Launch the configured daemon via wsl.exe. Returns immediately; never blocks.</summary>
    public void Launch(AppConfig config)
    {
        var spec = DaemonLaunchSpec.From(config, _port);
        LaunchRaw(spec.FileName, spec.Arguments);
    }

    /// <summary>
    /// Launch an arbitrary command non-blockingly. Public so process-mechanics tests can launch a
    /// long-running stand-in (e.g. `wsl.exe -d Ubuntu -e sleep 30`) without a real model.
    /// </summary>
    public void LaunchRaw(string fileName, IReadOnlyList<string> arguments)
    {
        lock (_gate)
        {
            StopLocked();

            var psi = new ProcessStartInfo
            {
                FileName = fileName,
                UseShellExecute = false,         // required for redirection; also avoids a shell window
                RedirectStandardOutput = true,   // so the child's stdout cannot fill a pipe and stall
                RedirectStandardError = true,
                CreateNoWindow = true,
            };
            foreach (var arg in arguments)
                psi.ArgumentList.Add(arg);

            var proc = new Process { StartInfo = psi, EnableRaisingEvents = true };

            // Drain output on Process's own background threads. NEVER WaitForExit on any UI path:
            // the daemon is persistent and would block forever. These handlers just keep the pipes
            // empty so the child does not stall on a full buffer.
            proc.OutputDataReceived += static (_, e) => { if (e.Data != null) Debug.WriteLine($"[daemon] {e.Data}"); };
            proc.ErrorDataReceived += static (_, e) => { if (e.Data != null) Debug.WriteLine($"[daemon:err] {e.Data}"); };

            proc.Start();
            proc.BeginOutputReadLine();   // async pipe drain - does NOT block the caller
            proc.BeginErrorReadLine();

            _process = proc;
            // Return immediately. No WaitForExit. The UI thread continues; startup proceeds to the
            // TCP connect (which awaits READY) without ever blocking on this process.
        }
    }

    public void Stop()
    {
        lock (_gate)
        {
            StopLocked();
        }
    }

    private void StopLocked()
    {
        if (_process is null) return;

        try
        {
            if (!_process.HasExited)
            {
                // Kill the wsl.exe relay. The daemon ALSO self-terminates on the persistent TCP
                // connection dropping (its backstop), so even a kill leaves no Python zombie.
                _process.Kill(entireProcessTree: true);
                _process.WaitForExit(3000);   // bounded wait, off the UI thread (called from Stop on exit)
            }
        }
        catch
        {
            // Best-effort: the process may already be gone.
        }
        finally
        {
            _process.Dispose();
            _process = null;
        }
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        Stop();
    }
}
```

- [ ] **Step 4: Run test to verify it passes (WIN11)**

Run: `powershell.exe -File scripts/win-tests.ps1`
Expected: PASS — `Launch_returns_immediately_and_does_not_block` confirms the launch is non-blocking (< 5s for a 30s sleep), the handle is captured, and `Stop()` kills it.

> **Escalation:** if `Launch_returns_immediately_and_does_not_block` fails (the call blocked), STOP. This is the daemon-hangs-the-UI failure mode — do not paper over it; find and remove any `WaitForExit`/synchronous read on the launch path and escalate the offending code.

- [ ] **Step 5: Commit**

```bash
git add src/WinSuperWhisper.App/Win32/DaemonProcessManager.cs tests/WinSuperWhisper.App.Tests/Win32/DaemonProcessManagerTests.cs
git commit -m "feat(daemon): non-blocking wsl.exe DaemonProcessManager with handle + kill"
```

---

## Task 6 (WIN11): `AppConfig` JSON store at `%APPDATA%\WinSuperWhisper\config.json`

App composition needs to load and save config. The store is a thin JSON serializer over `AppConfig` at the spec's path. The save/load round-trip is the only thing worth a smoke test; it is in `.App.Tests` because it touches the real `%APPDATA%` (a Windows env), though the serialization logic itself is trivial.

**Files:**

- Create: `src/WinSuperWhisper.App/ConfigStore.cs`
- Test: `tests/WinSuperWhisper.App.Tests/ConfigStoreTests.cs`

- [ ] **Step 1: Write the failing test (WIN11)**

```csharp
// tests/WinSuperWhisper.App.Tests/ConfigStoreTests.cs
using System.IO;
using WinSuperWhisper.App;
using WinSuperWhisper.Core.Models;
using Xunit;

namespace WinSuperWhisper.App.Tests;

public class ConfigStoreTests
{
    [Fact]
    public void Load_returns_defaults_when_file_absent()
    {
        var path = Path.Combine(Path.GetTempPath(), $"wsw-{System.Guid.NewGuid():N}.json");
        var store = new ConfigStore(path);
        var cfg = store.Load();
        Assert.Equal("Ubuntu", cfg.Distro);          // AppConfig default
        Assert.True(cfg.AutoType);                    // AppConfig default
        Assert.Equal(HotkeyCombo.Default, cfg.Hotkey);
    }

    [Fact]
    public void Save_then_load_round_trips()
    {
        var path = Path.Combine(Path.GetTempPath(), $"wsw-{System.Guid.NewGuid():N}.json");
        var store = new ConfigStore(path);
        var cfg = new AppConfig
        {
            Distro = "Ubuntu-22.04",
            ModelPathUnc = @"\\wsl$\Ubuntu-22.04\home\luna\models\base",
            DaemonScriptPathUnc = @"\\wsl$\Ubuntu-22.04\opt\whisper\whisper_daemon.py",
            Language = "en",
            AutoType = false,
        };
        store.Save(cfg);

        var loaded = new ConfigStore(path).Load();
        Assert.Equal("Ubuntu-22.04", loaded.Distro);
        Assert.Equal(cfg.ModelPathUnc, loaded.ModelPathUnc);
        Assert.Equal(cfg.DaemonScriptPathUnc, loaded.DaemonScriptPathUnc);
        Assert.Equal("en", loaded.Language);
        Assert.False(loaded.AutoType);

        File.Delete(path);
    }
}
```

- [ ] **Step 2: Run test to verify it fails (WIN11)**

Run: `powershell.exe -File scripts/win-tests.ps1`
Expected: FAIL — `ConfigStore` does not exist.

- [ ] **Step 3: Write the implementation**

```csharp
// src/WinSuperWhisper.App/ConfigStore.cs
using System;
using System.IO;
using System.Text.Json;
using WinSuperWhisper.Core.Models;

namespace WinSuperWhisper.App;

/// <summary>
/// Loads/saves AppConfig as JSON at %APPDATA%\WinSuperWhisper\config.json (path injectable for tests).
/// Missing or unreadable file yields fresh defaults so first launch always works.
/// </summary>
public sealed class ConfigStore
{
    private static readonly JsonSerializerOptions Options = new() { WriteIndented = true };
    private readonly string _path;

    public ConfigStore() : this(DefaultPath()) { }

    public ConfigStore(string path)
    {
        _path = path;
    }

    public static string DefaultPath()
    {
        var dir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "WinSuperWhisper");
        return Path.Combine(dir, "config.json");
    }

    public AppConfig Load()
    {
        try
        {
            if (!File.Exists(_path)) return new AppConfig();
            var json = File.ReadAllText(_path);
            return JsonSerializer.Deserialize<AppConfig>(json, Options) ?? new AppConfig();
        }
        catch
        {
            return new AppConfig();
        }
    }

    public void Save(AppConfig config)
    {
        var dir = Path.GetDirectoryName(_path);
        if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
        File.WriteAllText(_path, JsonSerializer.Serialize(config, Options));
    }
}
```

- [ ] **Step 4: Run test to verify it passes (WIN11)**

Run: `powershell.exe -File scripts/win-tests.ps1`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/WinSuperWhisper.App/ConfigStore.cs tests/WinSuperWhisper.App.Tests/ConfigStoreTests.cs
git commit -m "feat(app): JSON config store at %APPDATA%\\WinSuperWhisper\\config.json"
```

---

## Task 7 (WIN11): App composition — `App.xaml.cs` wires everything

Manual composition (no DI framework): on startup, build the real adapters and the orchestrator, run `StartupSequencer`, and wire focus capture/restore. On exit, run `ShutdownSequencer`. This is the seam where the Core ordering logic from Tasks 3-4 meets the real Win32 adapters from `03-adapters`, the UI from `04-ui`, and the daemon client/process from this file.

**Focus capture/restore (Phase 1 scope):** capture the foreground HWND on `Pressed` via `GetForegroundWindow`; restore on transcript arrival via `SetForegroundWindow`. The `AttachThreadInput` foreground-lock bypass is **DEFERRED to Phase 4** (spec Failure Paths > Focus drift). In Phase 1 we do the plain capture/restore and document that if the user clicks elsewhere while transcribing, restore may only flash the taskbar and the text lands in whatever window currently has focus. Do **not** build the Phase 4 hardening here.

The composition is driven by WPF lifecycle, so there is no clean Podman unit test of `App.xaml.cs` itself — its ordering logic was already extracted into `StartupSequencer`/`ShutdownSequencer` (tested in Podman, Tasks 3-4). The Windows smoke test asserts the app starts without throwing and the window is responsive (a proxy for "did not hang on daemon launch").

**Files:**

- Modify: `src/WinSuperWhisper.App/App.xaml.cs`
- Create: `src/WinSuperWhisper.App/Win32/FocusTracker.cs`
- Test: `tests/WinSuperWhisper.App.Tests/Win32/FocusTrackerTests.cs`

- [ ] **Step 1: Write the failing test (WIN11) for FocusTracker**

```csharp
// tests/WinSuperWhisper.App.Tests/Win32/FocusTrackerTests.cs
using WinSuperWhisper.App.Win32;
using Xunit;

namespace WinSuperWhisper.App.Tests.Win32;

public class FocusTrackerTests
{
    [Fact]
    public void Capture_records_a_nonzero_foreground_handle()
    {
        var tracker = new FocusTracker();
        tracker.Capture();
        // On an interactive Windows session there is always a foreground window.
        Assert.NotEqual(System.IntPtr.Zero, tracker.Captured);
    }

    [Fact]
    public void Restore_without_capture_is_a_noop_and_does_not_throw()
    {
        var tracker = new FocusTracker();
        // No Capture() called: Restore must be safe (returns false, no exception).
        Assert.False(tracker.Restore());
    }
}
```

- [ ] **Step 2: Run test to verify it fails (WIN11)**

Run: `powershell.exe -File scripts/win-tests.ps1`
Expected: FAIL — `FocusTracker` does not exist.

- [ ] **Step 3: Write FocusTracker**

```csharp
// src/WinSuperWhisper.App/Win32/FocusTracker.cs
using System;
using System.Runtime.InteropServices;

namespace WinSuperWhisper.App.Win32;

/// <summary>
/// Phase 1 focus capture/restore: snapshot the foreground window on hotkey press, restore it on
/// transcript arrival. This is the PLAIN version. Per the design spec (Failure Paths > Focus drift),
/// Windows blocks a background app from stealing focus, so if the user clicked elsewhere while
/// transcribing, SetForegroundWindow may only flash the taskbar and the text lands in whatever
/// window currently has focus. The AttachThreadInput foreground-lock bypass that hardens this is
/// DEFERRED TO PHASE 4 and deliberately not built here.
/// </summary>
public sealed class FocusTracker
{
    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetForegroundWindow(IntPtr hWnd);

    public IntPtr Captured { get; private set; } = IntPtr.Zero;

    public void Capture()
    {
        Captured = GetForegroundWindow();
    }

    /// <summary>Restore focus to the captured window. Returns false if nothing was captured.</summary>
    public bool Restore()
    {
        if (Captured == IntPtr.Zero) return false;
        return SetForegroundWindow(Captured);
    }
}
```

- [ ] **Step 4: Run test to verify it passes (WIN11)**

Run: `powershell.exe -File scripts/win-tests.ps1`
Expected: PASS.

- [ ] **Step 5: Wire App.xaml.cs (composition)**

```csharp
// src/WinSuperWhisper.App/App.xaml.cs
using System;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using WinSuperWhisper.App.Audio;
using WinSuperWhisper.App.Tray;
using WinSuperWhisper.App.Win32;
using WinSuperWhisper.App.Windows;
using WinSuperWhisper.Core.Daemon;
using WinSuperWhisper.Core.Interfaces;
using WinSuperWhisper.Core.Models;
using WinSuperWhisper.Core.Orchestrator;

namespace WinSuperWhisper.App;

/// <summary>
/// Manual composition root (no DI framework). Builds the real adapters, the daemon client/process,
/// and the orchestrator, then drives the startup/shutdown sequencers from Core. The startup launch
/// of the daemon is NON-BLOCKING (DaemonProcessManager) and the hotkey stays gated until READY, so
/// the WPF UI never hangs during model warm-up.
/// </summary>
public partial class App : Application
{
    private const int DaemonPort = 8765;

    private ConfigStore _configStore = null!;
    private AppConfig _config = null!;

    private DaemonProcessManager _processManager = null!;
    private IDaemonClient _daemonClient = null!;
    private IHotkeyService _hotkey = null!;
    private IAudioCapture _audio = null!;
    private ITextInjector _injector = null!;
    private IMonitorService _monitors = null!;
    private DictationOrchestrator _orchestrator = null!;
    private OverlayWindow _overlay = null!;
    private TrayIcon _tray = null!;
    private FocusTracker _focus = null!;

    private ShutdownSequencer _shutdownSequencer = null!;

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        ShutdownMode = ShutdownMode.OnExplicitShutdown;   // tray app: no main-window lifetime

        // 1. Load config.
        _configStore = new ConfigStore();
        _config = _configStore.Load();

        // 2. Build real adapters (from 03-adapters) and UI (from 04-ui).
        _hotkey = new Win32HotkeyService();
        _audio = new NAudioCapture();
        _injector = new Win32TextInjector();
        _monitors = new Win32MonitorService();
        _focus = new FocusTracker();

        _processManager = new DaemonProcessManager(DaemonPort);
        _daemonClient = new DaemonClient("127.0.0.1", DaemonPort);

        _overlay = new OverlayWindow(_monitors, _config);
        _tray = new TrayIcon();
        _tray.WarmingUp();   // tray shows "warming up" until READY

        // 3. Orchestrator wires the pipeline (hotkey -> capture -> WAV -> transcribe -> inject).
        _orchestrator = new DictationOrchestrator(
            _hotkey, _audio, _injector, _monitors, _daemonClient, _overlay, _config);

        // Focus capture on press; restore on transcript arrival (Phase 1 plain version).
        _hotkey.Pressed += (_, _) => _focus.Capture();
        _orchestrator.TranscriptArrived += (_, _) => _focus.Restore();

        _shutdownSequencer = new ShutdownSequencer(_daemonClient, _processManager);

        // Tray menu wiring.
        _tray.SettingsRequested += (_, _) => ShowSettings();
        _tray.ExitRequested += (_, _) => Shutdown();

        // 4. Run the startup sequence WITHOUT blocking the UI thread. The daemon launch is async
        //    (non-blocking Process.Start); ConnectAsync awaits READY; only then is the hotkey armed
        //    and the tray switched to idle. Fire-and-forget on a background task; failures escalate
        //    via a brief error toast (Phase 4) - in Phase 1 we surface to Debug + tray state.
        _ = RunStartupAsync();
    }

    private async Task RunStartupAsync()
    {
        try
        {
            var sequencer = new StartupSequencer(_processManager, _daemonClient, _hotkey);
            await sequencer.RunAsync(_config, CancellationToken.None).ConfigureAwait(true);

            // READY: tray idle (hotkey already armed inside the sequencer).
            _tray.Idle();
        }
        catch (Exception ex)
        {
            System.Diagnostics.Debug.WriteLine($"[startup] daemon did not become ready: {ex}");
            _tray.Error("daemon unavailable");
            // Hotkey stays gated; the user can fix the model path in Settings and relaunch.
        }
    }

    private void ShowSettings()
    {
        var win = new SettingsWindow(_monitors, _config, _configStore);
        win.ShowDialog();
    }

    protected override void OnExit(ExitEventArgs e)
    {
        // Clean shutdown: send [EXIT] then ensure the wsl.exe process is gone (no zombie).
        // Bounded so app exit cannot hang; the process kill is the no-zombie backstop.
        try
        {
            _shutdownSequencer.RunAsync().Wait(TimeSpan.FromSeconds(5));
        }
        catch (Exception ex)
        {
            System.Diagnostics.Debug.WriteLine($"[shutdown] {ex}");
            _processManager.Stop();   // last-resort backstop
        }

        _hotkey.Dispose();
        _audio.Dispose();
        _processManager.Dispose();
        _tray.Dispose();
        base.OnExit(e);
    }
}
```

> **Composition notes:** the exact constructor signatures of `Win32HotkeyService`, `NAudioCapture`, `Win32TextInjector`, `Win32MonitorService`, `OverlayWindow`, `SettingsWindow`, `TrayIcon`, `DaemonClient`, and `DictationOrchestrator` come from `03-adapters`, `04-ui`, and `02a-core`. If a real signature differs from what is shown (e.g. a tray method is named differently), adjust the call site to match the merged code — do NOT redesign the adapter. The contract-fixed names that must match verbatim are: `IHotkeyService.SetArmed`, `IDaemonClient.ConnectAsync/TranscribeAsync/ShutdownAsync`, `DictationOrchestrator`, and `AppConfig` fields (`Distro`, `ModelPathUnc`, `DaemonScriptPathUnc`). The `DictationOrchestrator.TranscriptArrived` event and `TrayIcon.WarmingUp/Idle/Error` come from 02a-core / 04-ui; if the merged code exposes them under other names, align the wiring to those names.

- [ ] **Step 6: Run the App.Tests smoke suite to verify composition compiles and starts (WIN11)**

Run: `powershell.exe -File scripts/win-tests.ps1`
Expected: PASS — all `.App.Tests` compile and pass, including the UI smoke test from `04-ui` (overlay appears/positions/dismisses) which exercises the composed app.

- [ ] **Step 7: Commit**

```bash
git add src/WinSuperWhisper.App/App.xaml.cs src/WinSuperWhisper.App/Win32/FocusTracker.cs tests/WinSuperWhisper.App.Tests/Win32/FocusTrackerTests.cs
git commit -m "feat(app): manual composition root, focus capture/restore, startup/shutdown wiring"
```

---

## Task 8 (WIN11): Full end-to-end — hold → speak → transcript typed into Notepad

The capstone. With a real small whisper model in WSL, prove the whole pipeline. This is **automated-where-possible plus manual-confirm**: the no-hang and no-zombie checks are scripted; the actual speak→type round-trip needs a human to speak and visually confirm the text landed.

The scripted parts live in `scripts/win-tests.ps1` (extended) so they run from WSL via `powershell.exe`. The manual part is an explicit checklist.

**Files:**

- Modify: `scripts/win-tests.ps1` (add e2e helper functions, run only when `-E2E` is passed)

- [ ] **Step 1: Add the scripted e2e helpers to `scripts/win-tests.ps1`**

Append these functions and an `-E2E` switch. Keep the existing `dotnet test` invocation as the default path; e2e helpers run only with `-E2E` so the normal CI tier stays fast and headless.

```powershell
# scripts/win-tests.ps1  (append)
param(
    [switch]$E2E,
    [string]$Distro = "Ubuntu"
)

# --- Scripted e2e assertions (the parts that do NOT need a human) -------------

function Assert-NoDaemonZombie {
    param([string]$Distro)
    # The no-zombie check the spec mandates: after [EXIT] on app close, there must be NO
    # `python3 whisper_daemon.py` left running in WSL.
    $found = wsl.exe -d $Distro -- pgrep -f whisper_daemon
    if ($LASTEXITCODE -eq 0 -and $found) {
        Write-Error "ZOMBIE: whisper_daemon still running in WSL after exit: $found"
        exit 1
    }
    Write-Host "OK: no whisper_daemon process left in WSL ($Distro)."
}

function Start-DaemonForManualE2E {
    param([string]$Distro)
    # Confirms the daemon launches and binds, and that launching does NOT hang. We start the app
    # by hand for the manual speak step; this helper just proves the daemon side is reachable.
    Write-Host "Checking the daemon launches and binds 0.0.0.0:8765 (no model load timing asserted here)..."
    # Port-reachability probe from the Windows side (client always uses 127.0.0.1).
    $probe = Test-NetConnection -ComputerName 127.0.0.1 -Port 8765 -InformationLevel Quiet
    if (-not $probe) {
        Write-Warning "Port 8765 not reachable yet - start WinSuperWhisper.exe first, wait for the tray to leave 'warming up'."
    } else {
        Write-Host "OK: 127.0.0.1:8765 reachable (daemon up and READY)."
    }
}

# --- Default path: dotnet test on .App.Tests --------------------------------

dotnet test tests/WinSuperWhisper.App.Tests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($E2E) {
    Start-DaemonForManualE2E -Distro $Distro
    Write-Host ""
    Write-Host "Now perform the MANUAL e2e checklist (see plan Task 8 Step 3), then press Enter to run the no-zombie check after you close the app."
    Read-Host | Out-Null
    Assert-NoDaemonZombie -Distro $Distro
}
```

- [ ] **Step 2: Run the scripted portion (WIN11)**

Run: `powershell.exe -File scripts/win-tests.ps1`
Expected: PASS — the normal `.App.Tests` tier is green (this is what `run-tests.sh` Tier 2 invokes).

The e2e portion is invoked separately and interactively:

Run: `powershell.exe -File scripts/win-tests.ps1 -E2E -Distro Ubuntu`
Expected: runs the daemon-reachability probe, prompts for the manual steps, then runs `Assert-NoDaemonZombie` after the app is closed.

- [ ] **Step 3: Execute the MANUAL e2e checklist (WIN11, human required)**

Prerequisites: a real (small) faster-whisper model directory exists in WSL (e.g. a `tiny` or `base` CTranslate2 model), and its `\\wsl$\<distro>\...` UNC path plus the daemon script UNC path are set in Settings.

Manual steps (perform on the Windows 11 machine, observe carefully):

1. **Launch responsiveness (no-hang assertion).** Start `WinSuperWhisper.exe`. The tray shows "warming up". **While it is warming up, open Settings from the tray and move the window.** The app window MUST be responsive (drag, resize, click) the entire time the model is loading. If the UI is frozen during warm-up → STOP and escalate (this is the daemon-hangs-the-UI failure).
2. **READY gate.** Before the tray leaves "warming up", press and release the hotkey. Nothing should happen (hotkey is gated). Wait until the tray switches to idle.
3. **Hold → speak → type.** Open **Notepad** and click into its text area so it has focus. Press and HOLD the hotkey (default Alt+Space). The red-square overlay appears with a live waveform. Speak a short sentence ("the quick brown fox"). Release the hotkey. The overlay switches to transcribing, then dismisses.
4. **Assert transcript typed into the real focused window.** Confirm the spoken sentence appears as typed text **in Notepad**. This is the core success criterion. If it lands in the wrong window → note whether you clicked away during transcribing; if focus restore was unreliable without you clicking away, STOP and escalate (do NOT improvise the Phase 4 `AttachThreadInput` hardening).
5. **Clean exit / no zombie.** Close the app from the tray "Exit". Then run the scripted check (or it runs automatically if you launched with `-E2E`):

   ```bash
   # from WSL:
   wsl.exe -d Ubuntu -- pgrep -f whisper_daemon ; echo "exit=$?"
   ```

   Expected: no PID printed and `exit=1` (pgrep found nothing). If a `python3 whisper_daemon.py` PID is still listed → STOP and escalate (zombie survived `[EXIT]`).

Record the outcome of each numbered step (pass/fail + note) in the PR description.

- [ ] **Step 4: Commit**

```bash
git add scripts/win-tests.ps1
git commit -m "test(e2e): scripted no-zombie + daemon-reachability checks and manual e2e checklist"
```

---

## Self-review crosscheck (run before opening the PR)

- **Spec coverage:** Startup data flow (load config → launch daemon async → connect+READY → arm hotkey) is Tasks 3 + 7. Shutdown `[EXIT]` + no zombie is Tasks 4 + 5 + 8. Daemon-not-running auto-restart+retry-once is Task 3. Focus capture/restore (plain, Phase 4 deferred) is Task 7. Full e2e is Task 8.
- **Contract names verbatim:** `IDaemonClient.ConnectAsync/TranscribeAsync/ShutdownAsync`, `IHotkeyService.SetArmed`, `DictationOrchestrator`, `AppConfig.Distro/ModelPathUnc/DaemonScriptPathUnc` — all used as defined in the contract.
- **The load-bearing detail:** `DaemonProcessManager.LaunchRaw` uses `UseShellExecute=false`, redirected stdout/stderr drained via `BeginOutputReadLine`/`BeginErrorReadLine`, and never calls `WaitForExit` on the launch path. Task 5's `Launch_returns_immediately_and_does_not_block` test guards it.
- **No placeholders:** every code step is complete C#/PowerShell.

---

## Exit conditions (all must be green)

This file is the FINAL Phase 1 piece. It depends on `03-adapters` and `04-ui` being merged, and it ships as the capstone of the Phase 1 PR set. All of the following must be true:

- [ ] **Podman tier green:** `WslPathTests`, `DaemonLaunchSpecTests`, `StartupSequencerTests`, `ShutdownSequencerTests` all pass via `dotnet test tests/WinSuperWhisper.Tests`.
- [ ] **Daemon launches async (no UI hang):** `DaemonProcessManager.Launch` returns immediately; `Launch_returns_immediately_and_does_not_block` passes on WIN11, and the manual launch-responsiveness step (Task 8 step 1) confirms the app window stays responsive during warm-up.
- [ ] **READY gates the hotkey:** the hotkey stays gated (`SetArmed(true)` only after `READY`); proven by `StartupSequencerTests` (Podman) and the manual READY-gate step (Task 8 step 2).
- [ ] **Full e2e on Win11:** hold → speak → the transcript is typed into a real focused window (Notepad), per the manual checklist (Task 8 step 3-4).
- [ ] **`[EXIT]` on close leaves no zombie:** `wsl.exe -d <distro> -- pgrep -f whisper_daemon` finds nothing after app exit (`Assert-NoDaemonZombie`, Task 8 step 5).
- [ ] **Focus restore behaves per Phase 1 scope:** plain `GetForegroundWindow`/`SetForegroundWindow` capture/restore works for the focused-window case; the `AttachThreadInput` hardening is documented as DEFERRED to Phase 4 and not built here.
- [ ] **`run-tests.sh` green** (Podman tier then `powershell.exe -File scripts/win-tests.ps1`), exiting non-zero on any failure.
