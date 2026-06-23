# WinSuperWhisper Phase 1 - Core (Skeleton) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `WinSuperWhisper.Core` (`net8.0`) class library - the five Windows-hiding interfaces, the config/audio/IPC/orchestration logic - so the entire load-bearing business logic compiles and is fully tested on Linux in Podman, with no WPF and no NAudio.

**Architecture:** Every Windows API is hidden behind an interface defined in Core. The orchestrator wires those interfaces together as pure logic. WAV encoding, config persistence, the TCP frame protocol, and the daemon client are all pure `net8.0` code with injected seams (a path for config, an in-process `TcpListener` for the daemon client), so the whole layer is exercised by xUnit + Moq under Podman. No real daemon, no Python, no Windows in this file.

**Tech Stack:** C# / .NET 8 (`net8.0`, nullable enabled), `System.Text.Json`, `System.Net.Sockets.TcpClient`/`TcpListener`, xUnit, Moq. All tests run in a Podman container (`mcr.microsoft.com/dotnet/sdk:8.0`).

---

## Provenance and authority

- **Design spec (authoritative for behavior):** `/home/luna/projects/firstmate/docs/superpowers/specs/2026-06-22-winsuperwhisper-design.md`
- **Shared contract (authoritative for names/signatures/wire format):** every interface signature, model shape, and IPC frame in this plan is copied verbatim from the Phase 1 shared contract. Do **not** redesign any of them.
- This is a **standalone git repo** named `WinSuperWhisper` with `WinSuperWhisper.sln` at its root. It does **not** live under firstmate. All paths below are relative to that repo root.

## Dependency and parallelism

- **Depends on `01-foundation`:** the repo, `WinSuperWhisper.sln`, the `src/WinSuperWhisper.Core` project, and the `tests/WinSuperWhisper.Tests` project (xUnit + Moq, TFM `net8.0`, references Core only) already exist and build. This file adds source files into those existing projects; it does not create the `.csproj` files or the solution.
- **Runs in parallel with `02b-daemon`** (the Python daemon). The two share no code: `02b-daemon` implements the other side of the same wire format in Python. They agree only through the contract's IPC section, never through shared source.

## Tag: PODMAN

Every task in this file is verifiable on Linux. The Core test project references Core only and must never reference WPF (`PresentationFramework`, `PresentationCore`, `WindowsBase`) or NAudio - that absence is the Podman boundary and is the guardrail that keeps Core portable.

### Running the tests (container-sandbox workflow)

All `dotnet test` commands below run inside a Podman container so the host needs no .NET SDK. From the repo root:

```bash
podman run --rm -t \
  -v "$PWD":/work:Z \
  -w /work \
  mcr.microsoft.com/dotnet/sdk:8.0 \
  dotnet test tests/WinSuperWhisper.Tests --filter "<FilterExpression>"
```

For brevity, each step writes the command as `dotnet test tests/WinSuperWhisper.Tests --filter "<...>"`; **always run it through the Podman wrapper above** (substituting the filter). The full suite for this file (no filter) is:

```bash
podman run --rm -t -v "$PWD":/work:Z -w /work \
  mcr.microsoft.com/dotnet/sdk:8.0 \
  dotnet test tests/WinSuperWhisper.Tests
```

The daemon-client tests bind a `TcpListener` on `127.0.0.1:0` (an ephemeral loopback port) inside the same container, so they need no network access beyond loopback and no real daemon.

## Escalation contract (read once, applies to every task)

- **Exit conditions are binary.** A task is done only when its test command prints PASS for the named test(s) and the tree is green. "Almost passing" is not done.
- **Mechanical failures get a bounded 2-attempt retry.** A flaky restore, a transient container pull, a port that was momentarily busy: retry at most twice. If it still fails, stop and escalate with the exact error.
- **Judgment calls stop and escalate immediately - never guess.** This includes any ambiguity in the wire format (frame layout, the exact READY/EXIT byte payloads, endianness, the handshake ordering), any temptation to weaken or delete a test to make it pass, or any need for a credential or machine you do not have. The IPC protocol is fixed by the contract; if reality seems to disagree with it, that is an escalation, not an improvisation. Do **not** invent protocol details.
- **Never commit a red tree.** One commit per task, conventional-commit message, only after the task's tests pass.

---

### Task 1: Models (records, structs, enums)

Trivial compiled types copied verbatim from the contract. The "test" is that they compile and a tiny model assertion passes (`HotkeyCombo.Default`).

**Files:**

- Create: `src/WinSuperWhisper.Core/Models/HotkeyCombo.cs`
- Create: `src/WinSuperWhisper.Core/Models/MonitorInfo.cs`
- Create: `src/WinSuperWhisper.Core/Models/AudioLevel.cs`
- Create: `src/WinSuperWhisper.Core/Models/InjectionResult.cs`
- Create: `src/WinSuperWhisper.Core/Models/RecorderState.cs`
- Create: `src/WinSuperWhisper.Core/Models/AppConfig.cs`
- Test: `tests/WinSuperWhisper.Tests/Models/HotkeyComboTests.cs`

- [ ] **Step 1: Write the failing test**

`tests/WinSuperWhisper.Tests/Models/HotkeyComboTests.cs`

```csharp
using WinSuperWhisper.Core.Models;
using Xunit;

namespace WinSuperWhisper.Tests.Models;

public class HotkeyComboTests
{
    [Fact]
    public void Default_IsAltSpace()
    {
        var combo = HotkeyCombo.Default;

        Assert.Equal(0x0001u, combo.Modifiers); // MOD_ALT
        Assert.Equal(0x20u, combo.VirtualKey);  // VK_SPACE
    }

    [Fact]
    public void Default_EqualsAnEquivalentValue()
    {
        Assert.Equal(new HotkeyCombo(0x0001, 0x20), HotkeyCombo.Default);
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `dotnet test tests/WinSuperWhisper.Tests --filter "FullyQualifiedName~HotkeyComboTests"`
Expected: FAIL - compile error, `The type or namespace name 'HotkeyCombo' could not be found` (the model does not exist yet).

- [ ] **Step 3: Write minimal implementation**

`src/WinSuperWhisper.Core/Models/HotkeyCombo.cs`

```csharp
namespace WinSuperWhisper.Core.Models;

public sealed record HotkeyCombo(uint Modifiers, uint VirtualKey)
{
    // Modifiers are Win32 MOD_* flags (MOD_CONTROL=0x0002, MOD_ALT=0x0001, MOD_SHIFT=0x0004, MOD_WIN=0x0008)
    public static HotkeyCombo Default => new(0x0001 /*MOD_ALT*/, 0x20 /*VK_SPACE*/);
}
```

`src/WinSuperWhisper.Core/Models/MonitorInfo.cs`

```csharp
namespace WinSuperWhisper.Core.Models;

public sealed record MonitorInfo(
    string Id,            // stable device key, e.g. \\.\DISPLAY1
    string Name,
    int WidthPx,
    int HeightPx,
    double DpiScale,      // 1.0 at 96 DPI, 1.5 at 150%
    int WorkAreaLeft,
    int WorkAreaTop,
    int WorkAreaRight,
    int WorkAreaBottom,
    bool IsPrimary);
```

`src/WinSuperWhisper.Core/Models/AudioLevel.cs`

```csharp
namespace WinSuperWhisper.Core.Models;

public readonly record struct AudioLevel(float Peak);   // normalized 0.0..1.0
```

`src/WinSuperWhisper.Core/Models/InjectionResult.cs`

```csharp
namespace WinSuperWhisper.Core.Models;

public enum InjectionResult { Typed, ClipboardFallback, Failed }
```

`src/WinSuperWhisper.Core/Models/RecorderState.cs`

```csharp
namespace WinSuperWhisper.Core.Models;

public enum RecorderState { Idle, WarmingUp, Recording, Transcribing }
```

`src/WinSuperWhisper.Core/Models/AppConfig.cs`

```csharp
namespace WinSuperWhisper.Core.Models;

public sealed class AppConfig
{
    public string Distro { get; set; } = "Ubuntu";
    public string ModelPathUnc { get; set; } = "";   // \\wsl$\<distro>\... selected in Settings
    public string DaemonScriptPathUnc { get; set; } = "";
    public string Language { get; set; } = "auto";
    public string MonitorId { get; set; } = "";       // empty = primary
    public HotkeyCombo Hotkey { get; set; } = HotkeyCombo.Default;
    public bool AutoType { get; set; } = true;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `dotnet test tests/WinSuperWhisper.Tests --filter "FullyQualifiedName~HotkeyComboTests"`
Expected: PASS - 2 tests passed.

- [ ] **Step 5: Commit**

```bash
git add src/WinSuperWhisper.Core/Models tests/WinSuperWhisper.Tests/Models/HotkeyComboTests.cs
git commit -m "feat(core): add Phase 1 domain models"
```

---

### Task 2: The five interfaces

Compiled-but-trivial declarations copied verbatim from the contract. They reference the Task 1 models. There is no behavior to test beyond compilation; the proof is a test that the assembly exposes all five interface types, which fails to compile until they exist.

**Files:**

- Create: `src/WinSuperWhisper.Core/Interfaces/IHotkeyService.cs`
- Create: `src/WinSuperWhisper.Core/Interfaces/IAudioCapture.cs`
- Create: `src/WinSuperWhisper.Core/Interfaces/ITextInjector.cs`
- Create: `src/WinSuperWhisper.Core/Interfaces/IMonitorService.cs`
- Create: `src/WinSuperWhisper.Core/Interfaces/IDaemonClient.cs`
- Test: `tests/WinSuperWhisper.Tests/Interfaces/InterfaceShapeTests.cs`

- [ ] **Step 1: Write the failing test**

`tests/WinSuperWhisper.Tests/Interfaces/InterfaceShapeTests.cs`

```csharp
using System;
using WinSuperWhisper.Core.Interfaces;
using Xunit;

namespace WinSuperWhisper.Tests.Interfaces;

public class InterfaceShapeTests
{
    [Theory]
    [InlineData(typeof(IHotkeyService))]
    [InlineData(typeof(IAudioCapture))]
    [InlineData(typeof(ITextInjector))]
    [InlineData(typeof(IMonitorService))]
    [InlineData(typeof(IDaemonClient))]
    public void Interface_IsPublicInterface(Type t)
    {
        Assert.True(t.IsInterface, $"{t.Name} should be an interface");
        Assert.True(t.IsPublic, $"{t.Name} should be public");
    }

    [Fact]
    public void HotkeyService_IsDisposable()
    {
        Assert.True(typeof(IDisposable).IsAssignableFrom(typeof(IHotkeyService)));
    }

    [Fact]
    public void DaemonClient_IsAsyncDisposable()
    {
        Assert.True(typeof(IAsyncDisposable).IsAssignableFrom(typeof(IDaemonClient)));
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `dotnet test tests/WinSuperWhisper.Tests --filter "FullyQualifiedName~InterfaceShapeTests"`
Expected: FAIL - compile error, `The type or namespace name 'IHotkeyService' could not be found` (and the other four).

- [ ] **Step 3: Write minimal implementation**

`src/WinSuperWhisper.Core/Interfaces/IHotkeyService.cs`

```csharp
using WinSuperWhisper.Core.Models;

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
```

`src/WinSuperWhisper.Core/Interfaces/IAudioCapture.cs`

```csharp
using WinSuperWhisper.Core.Models;

namespace WinSuperWhisper.Core.Interfaces;

public interface IAudioCapture : IDisposable
{
    event EventHandler<AudioLevel>? LevelAvailable;   // ~30fps amplitude for waveform
    void Start();
    void Stop();
    byte[] GetCapturedPcm();     // 16 kHz mono 16-bit little-endian PCM, no header
    bool IsCapturing { get; }
}
```

`src/WinSuperWhisper.Core/Interfaces/ITextInjector.cs`

```csharp
using WinSuperWhisper.Core.Models;

namespace WinSuperWhisper.Core.Interfaces;

public interface ITextInjector
{
    InjectionResult Inject(string text);
}
```

`src/WinSuperWhisper.Core/Interfaces/IMonitorService.cs`

```csharp
using System.Collections.Generic;
using WinSuperWhisper.Core.Models;

namespace WinSuperWhisper.Core.Interfaces;

public interface IMonitorService
{
    IReadOnlyList<MonitorInfo> GetMonitors();
    MonitorInfo? FindById(string id);
}
```

`src/WinSuperWhisper.Core/Interfaces/IDaemonClient.cs`

```csharp
using System.Threading;
using System.Threading.Tasks;

namespace WinSuperWhisper.Core.Interfaces;

public interface IDaemonClient : IAsyncDisposable
{
    event EventHandler? Disconnected;
    bool IsReady { get; }
    Task ConnectAsync(CancellationToken ct);          // connects then awaits READY
    Task<string> TranscribeAsync(byte[] wavBytes, CancellationToken ct);
    Task ShutdownAsync();                              // sends [EXIT], closes socket
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `dotnet test tests/WinSuperWhisper.Tests --filter "FullyQualifiedName~InterfaceShapeTests"`
Expected: PASS - 7 tests passed (5 theory cases + 2 facts).

- [ ] **Step 5: Commit**

```bash
git add src/WinSuperWhisper.Core/Interfaces tests/WinSuperWhisper.Tests/Interfaces/InterfaceShapeTests.cs
git commit -m "feat(core): add the five Windows-hiding interfaces"
```

---

### Task 3: AppConfig load/save (round-trip JSON with an injected path)

Pure persistence logic. The path is injected so it tests on Linux; production code in the App project will pass `%APPDATA%\WinSuperWhisper\config.json`. `System.Text.Json`. Load of a missing file returns defaults; save then load round-trips.

**Files:**

- Create: `src/WinSuperWhisper.Core/Models/AppConfigStore.cs`
- Test: `tests/WinSuperWhisper.Tests/Models/AppConfigStoreTests.cs`

- [ ] **Step 1: Write the failing test**

`tests/WinSuperWhisper.Tests/Models/AppConfigStoreTests.cs`

```csharp
using System;
using System.IO;
using WinSuperWhisper.Core.Models;
using Xunit;

namespace WinSuperWhisper.Tests.Models;

public class AppConfigStoreTests : IDisposable
{
    private readonly string _dir;
    private readonly string _path;

    public AppConfigStoreTests()
    {
        _dir = Path.Combine(Path.GetTempPath(), "wsw-cfg-" + Guid.NewGuid().ToString("N"));
        _path = Path.Combine(_dir, "config.json");
    }

    public void Dispose()
    {
        if (Directory.Exists(_dir))
            Directory.Delete(_dir, recursive: true);
    }

    [Fact]
    public void Load_MissingFile_ReturnsDefaults()
    {
        var store = new AppConfigStore(_path);

        var cfg = store.Load();

        Assert.Equal("Ubuntu", cfg.Distro);
        Assert.Equal("auto", cfg.Language);
        Assert.True(cfg.AutoType);
        Assert.Equal(HotkeyCombo.Default, cfg.Hotkey);
    }

    [Fact]
    public void Save_CreatesDirectoryAndFile()
    {
        var store = new AppConfigStore(_path);

        store.Save(new AppConfig());

        Assert.True(File.Exists(_path));
    }

    [Fact]
    public void SaveThenLoad_RoundTripsAllFields()
    {
        var store = new AppConfigStore(_path);
        var original = new AppConfig
        {
            Distro = "Debian",
            ModelPathUnc = @"\\wsl$\Debian\models\large-v3",
            DaemonScriptPathUnc = @"\\wsl$\Debian\opt\wsw\whisper_daemon.py",
            Language = "en",
            MonitorId = @"\\.\DISPLAY2",
            Hotkey = new HotkeyCombo(0x0002 /*MOD_CONTROL*/, 0x42 /*VK_B*/),
            AutoType = false,
        };

        store.Save(original);
        var loaded = store.Load();

        Assert.Equal(original.Distro, loaded.Distro);
        Assert.Equal(original.ModelPathUnc, loaded.ModelPathUnc);
        Assert.Equal(original.DaemonScriptPathUnc, loaded.DaemonScriptPathUnc);
        Assert.Equal(original.Language, loaded.Language);
        Assert.Equal(original.MonitorId, loaded.MonitorId);
        Assert.Equal(original.Hotkey, loaded.Hotkey);
        Assert.Equal(original.AutoType, loaded.AutoType);
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `dotnet test tests/WinSuperWhisper.Tests --filter "FullyQualifiedName~AppConfigStoreTests"`
Expected: FAIL - compile error, `The type or namespace name 'AppConfigStore' could not be found`.

- [ ] **Step 3: Write minimal implementation**

`src/WinSuperWhisper.Core/Models/AppConfigStore.cs`

```csharp
using System.IO;
using System.Text.Json;

namespace WinSuperWhisper.Core.Models;

/// <summary>
/// Loads and saves <see cref="AppConfig"/> as JSON at an injected path.
/// The App project constructs this with %APPDATA%\WinSuperWhisper\config.json;
/// tests inject a temp path so persistence is verifiable on Linux.
/// </summary>
public sealed class AppConfigStore
{
    private static readonly JsonSerializerOptions Options = new()
    {
        WriteIndented = true,
    };

    private readonly string _path;

    public AppConfigStore(string path)
    {
        _path = path;
    }

    /// <summary>Returns the persisted config, or a fresh default config if no file exists.</summary>
    public AppConfig Load()
    {
        if (!File.Exists(_path))
            return new AppConfig();

        var json = File.ReadAllText(_path);
        return JsonSerializer.Deserialize<AppConfig>(json, Options) ?? new AppConfig();
    }

    /// <summary>Writes the config as indented JSON, creating the parent directory if needed.</summary>
    public void Save(AppConfig config)
    {
        var dir = Path.GetDirectoryName(_path);
        if (!string.IsNullOrEmpty(dir))
            Directory.CreateDirectory(dir);

        var json = JsonSerializer.Serialize(config, Options);
        File.WriteAllText(_path, json);
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `dotnet test tests/WinSuperWhisper.Tests --filter "FullyQualifiedName~AppConfigStoreTests"`
Expected: PASS - 3 tests passed.

- [ ] **Step 5: Commit**

```bash
git add src/WinSuperWhisper.Core/Models/AppConfigStore.cs tests/WinSuperWhisper.Tests/Models/AppConfigStoreTests.cs
git commit -m "feat(core): add AppConfigStore JSON persistence with injected path"
```

---

### Task 4: WavEncoder (PCM 16kHz mono 16-bit LE -> in-memory WAV bytes)

Encodes raw PCM into a complete in-memory WAV file (the exact byte layout the daemon parses with the stdlib `wave` module). 44-byte canonical RIFF/WAVE header followed by the PCM data, no temp file. Must handle the empty-PCM case.

**Files:**

- Create: `src/WinSuperWhisper.Core/Audio/WavEncoder.cs`
- Test: `tests/WinSuperWhisper.Tests/Audio/WavEncoderTests.cs`

- [ ] **Step 1: Write the failing test**

`tests/WinSuperWhisper.Tests/Audio/WavEncoderTests.cs`

```csharp
using System;
using System.Buffers.Binary;
using System.Text;
using WinSuperWhisper.Core.Audio;
using Xunit;

namespace WinSuperWhisper.Tests.Audio;

public class WavEncoderTests
{
    private const int SampleRate = 16000;
    private const int Channels = 1;
    private const int BitsPerSample = 16;

    private static string Ascii(byte[] b, int offset, int len) =>
        Encoding.ASCII.GetString(b, offset, len);

    [Fact]
    public void Encode_ProducesCanonical44ByteHeader()
    {
        // 4 samples = 8 bytes of PCM
        var pcm = new byte[] { 1, 0, 2, 0, 3, 0, 4, 0 };

        var wav = WavEncoder.Encode(pcm);

        Assert.Equal(44 + pcm.Length, wav.Length);

        // RIFF chunk
        Assert.Equal("RIFF", Ascii(wav, 0, 4));
        Assert.Equal((uint)(36 + pcm.Length), BinaryPrimitives.ReadUInt32LittleEndian(wav.AsSpan(4, 4)));
        Assert.Equal("WAVE", Ascii(wav, 8, 4));

        // fmt subchunk
        Assert.Equal("fmt ", Ascii(wav, 12, 4));
        Assert.Equal(16u, BinaryPrimitives.ReadUInt32LittleEndian(wav.AsSpan(16, 4)));          // PCM fmt chunk size
        Assert.Equal((ushort)1, BinaryPrimitives.ReadUInt16LittleEndian(wav.AsSpan(20, 2)));     // AudioFormat=PCM
        Assert.Equal((ushort)Channels, BinaryPrimitives.ReadUInt16LittleEndian(wav.AsSpan(22, 2)));
        Assert.Equal((uint)SampleRate, BinaryPrimitives.ReadUInt32LittleEndian(wav.AsSpan(24, 4)));
        Assert.Equal((uint)(SampleRate * Channels * BitsPerSample / 8),
            BinaryPrimitives.ReadUInt32LittleEndian(wav.AsSpan(28, 4)));                          // byte rate
        Assert.Equal((ushort)(Channels * BitsPerSample / 8),
            BinaryPrimitives.ReadUInt16LittleEndian(wav.AsSpan(32, 2)));                          // block align
        Assert.Equal((ushort)BitsPerSample, BinaryPrimitives.ReadUInt16LittleEndian(wav.AsSpan(34, 2)));

        // data subchunk
        Assert.Equal("data", Ascii(wav, 36, 4));
        Assert.Equal((uint)pcm.Length, BinaryPrimitives.ReadUInt32LittleEndian(wav.AsSpan(40, 4)));
    }

    [Fact]
    public void Encode_DataSubchunkEqualsInputPcm()
    {
        var pcm = new byte[] { 10, 0, 20, 0, 255, 127, 0, 128 };

        var wav = WavEncoder.Encode(pcm);

        Assert.Equal(pcm, wav.AsSpan(44).ToArray());
    }

    [Fact]
    public void Encode_EmptyPcm_ProducesHeaderOnlyWithZeroDataSize()
    {
        var wav = WavEncoder.Encode(Array.Empty<byte>());

        Assert.Equal(44, wav.Length);
        Assert.Equal("RIFF", Ascii(wav, 0, 4));
        Assert.Equal(36u, BinaryPrimitives.ReadUInt32LittleEndian(wav.AsSpan(4, 4)));   // 36 + 0
        Assert.Equal("data", Ascii(wav, 36, 4));
        Assert.Equal(0u, BinaryPrimitives.ReadUInt32LittleEndian(wav.AsSpan(40, 4)));   // empty data subchunk
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `dotnet test tests/WinSuperWhisper.Tests --filter "FullyQualifiedName~WavEncoderTests"`
Expected: FAIL - compile error, `The type or namespace name 'WavEncoder' could not be found`.

- [ ] **Step 3: Write minimal implementation**

`src/WinSuperWhisper.Core/Audio/WavEncoder.cs`

```csharp
using System.Buffers.Binary;

namespace WinSuperWhisper.Core.Audio;

/// <summary>
/// Encodes raw PCM (16 kHz, mono, 16-bit little-endian, no header) into a complete
/// in-memory WAV file with a canonical 44-byte RIFF/WAVE header. No temp file.
/// The daemon parses these bytes with Python's stdlib <c>wave</c> module.
/// </summary>
public static class WavEncoder
{
    public const int SampleRate = 16000;
    public const int Channels = 1;
    public const int BitsPerSample = 16;

    private const int HeaderSize = 44;

    public static byte[] Encode(byte[] pcm)
    {
        var dataLen = pcm.Length;
        var wav = new byte[HeaderSize + dataLen];
        var span = wav.AsSpan();

        // RIFF chunk descriptor
        WriteAscii(span, 0, "RIFF");
        BinaryPrimitives.WriteUInt32LittleEndian(span.Slice(4, 4), (uint)(36 + dataLen));
        WriteAscii(span, 8, "WAVE");

        // fmt subchunk
        WriteAscii(span, 12, "fmt ");
        BinaryPrimitives.WriteUInt32LittleEndian(span.Slice(16, 4), 16);               // PCM fmt chunk size
        BinaryPrimitives.WriteUInt16LittleEndian(span.Slice(20, 2), 1);                // AudioFormat = PCM
        BinaryPrimitives.WriteUInt16LittleEndian(span.Slice(22, 2), Channels);
        BinaryPrimitives.WriteUInt32LittleEndian(span.Slice(24, 4), SampleRate);
        BinaryPrimitives.WriteUInt32LittleEndian(span.Slice(28, 4),
            (uint)(SampleRate * Channels * BitsPerSample / 8));                         // byte rate
        BinaryPrimitives.WriteUInt16LittleEndian(span.Slice(32, 2),
            (ushort)(Channels * BitsPerSample / 8));                                    // block align
        BinaryPrimitives.WriteUInt16LittleEndian(span.Slice(34, 2), BitsPerSample);

        // data subchunk
        WriteAscii(span, 36, "data");
        BinaryPrimitives.WriteUInt32LittleEndian(span.Slice(40, 4), (uint)dataLen);
        pcm.CopyTo(span.Slice(HeaderSize));

        return wav;
    }

    private static void WriteAscii(Span<byte> span, int offset, string tag)
    {
        for (var i = 0; i < tag.Length; i++)
            span[offset + i] = (byte)tag[i];
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `dotnet test tests/WinSuperWhisper.Tests --filter "FullyQualifiedName~WavEncoderTests"`
Expected: PASS - 3 tests passed.

- [ ] **Step 5: Commit**

```bash
git add src/WinSuperWhisper.Core/Audio/WavEncoder.cs tests/WinSuperWhisper.Tests/Audio/WavEncoderTests.cs
git commit -m "feat(core): add WavEncoder (PCM -> in-memory WAV bytes)"
```

---

### Task 5: FrameProtocol (length-prefixed frames + READY/EXIT constants)

Static helpers to write/read a `[4-byte little-endian length][payload]` frame on a `Stream`, plus the exact READY (ASCII `READY`) and EXIT (ASCII `[EXIT]`) payload constants from the contract. This is the wire format both the C# client and the Python daemon agree on.

**Files:**

- Create: `src/WinSuperWhisper.Core/Daemon/FrameProtocol.cs`
- Test: `tests/WinSuperWhisper.Tests/Daemon/FrameProtocolTests.cs`

- [ ] **Step 1: Write the failing test**

`tests/WinSuperWhisper.Tests/Daemon/FrameProtocolTests.cs`

```csharp
using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using WinSuperWhisper.Core.Daemon;
using Xunit;

namespace WinSuperWhisper.Tests.Daemon;

public class FrameProtocolTests
{
    [Fact]
    public void ReadyPayload_IsExactlyFiveAsciiBytes()
    {
        Assert.Equal(new byte[] { (byte)'R', (byte)'E', (byte)'A', (byte)'D', (byte)'Y' },
            FrameProtocol.ReadyPayload);
    }

    [Fact]
    public void ExitPayload_IsExactlySixAsciiBytes()
    {
        Assert.Equal(
            new byte[] { (byte)'[', (byte)'E', (byte)'X', (byte)'I', (byte)'T', (byte)']' },
            FrameProtocol.ExitPayload);
    }

    [Fact]
    public async Task WriteThenRead_RoundTripsPayload()
    {
        var payload = Encoding.UTF8.GetBytes("hello daemon");
        using var stream = new MemoryStream();

        await FrameProtocol.WriteFrameAsync(stream, payload, CancellationToken.None);
        stream.Position = 0;
        var read = await FrameProtocol.ReadFrameAsync(stream, CancellationToken.None);

        Assert.Equal(payload, read);
    }

    [Fact]
    public async Task WriteFrame_PrependsFourByteLittleEndianLength()
    {
        var payload = new byte[] { 9, 8, 7 };
        using var stream = new MemoryStream();

        await FrameProtocol.WriteFrameAsync(stream, payload, CancellationToken.None);

        var bytes = stream.ToArray();
        Assert.Equal(new byte[] { 3, 0, 0, 0 }, bytes.Take(4).ToArray()); // length 3, little-endian
        Assert.Equal(payload, bytes.Skip(4).ToArray());
    }

    [Fact]
    public void IsReady_TrueForReadyFrameOnly()
    {
        Assert.True(FrameProtocol.IsReady(FrameProtocol.ReadyPayload));
        Assert.False(FrameProtocol.IsReady(Encoding.ASCII.GetBytes("READYX")));
        Assert.False(FrameProtocol.IsReady(Encoding.ASCII.GetBytes("nope")));
    }

    [Fact]
    public async Task ReadFrame_EmptyStream_ReturnsNullOnGracefulEof()
    {
        using var stream = new MemoryStream(Array.Empty<byte>());

        var read = await FrameProtocol.ReadFrameAsync(stream, CancellationToken.None);

        Assert.Null(read);
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `dotnet test tests/WinSuperWhisper.Tests --filter "FullyQualifiedName~FrameProtocolTests"`
Expected: FAIL - compile error, `The type or namespace name 'FrameProtocol' could not be found`.

- [ ] **Step 3: Write minimal implementation**

`src/WinSuperWhisper.Core/Daemon/FrameProtocol.cs`

```csharp
using System;
using System.Buffers.Binary;
using System.IO;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace WinSuperWhisper.Core.Daemon;

/// <summary>
/// The fixed wire format shared with the Python daemon: every message is a frame of
/// <c>[4-byte little-endian uint32 length N][N payload bytes]</c>. Frames are disambiguated
/// by payload content - there is no separate type byte.
/// </summary>
public static class FrameProtocol
{
    /// <summary>READY control frame payload (daemon -> client): exactly the 5 ASCII bytes "READY".</summary>
    public static byte[] ReadyPayload => Encoding.ASCII.GetBytes("READY");

    /// <summary>EXIT control frame payload (client -> daemon): exactly the 6 ASCII bytes "[EXIT]".</summary>
    public static byte[] ExitPayload => Encoding.ASCII.GetBytes("[EXIT]");

    /// <summary>True iff the payload is exactly the READY control frame.</summary>
    public static bool IsReady(byte[] payload) =>
        payload.Length == 5 &&
        payload[0] == (byte)'R' && payload[1] == (byte)'E' && payload[2] == (byte)'A' &&
        payload[3] == (byte)'D' && payload[4] == (byte)'Y';

    /// <summary>Writes a single frame: 4-byte LE length prefix followed by the payload.</summary>
    public static async Task WriteFrameAsync(Stream stream, byte[] payload, CancellationToken ct)
    {
        var header = new byte[4];
        BinaryPrimitives.WriteUInt32LittleEndian(header, (uint)payload.Length);
        await stream.WriteAsync(header, ct).ConfigureAwait(false);
        await stream.WriteAsync(payload, ct).ConfigureAwait(false);
        await stream.FlushAsync(ct).ConfigureAwait(false);
    }

    /// <summary>
    /// Reads one frame. Returns the payload, or <c>null</c> if the stream reaches a clean EOF
    /// before any length bytes arrive (the peer closed the connection between frames).
    /// </summary>
    public static async Task<byte[]?> ReadFrameAsync(Stream stream, CancellationToken ct)
    {
        var header = new byte[4];
        var got = await ReadExactlyOrEofAsync(stream, header, ct).ConfigureAwait(false);
        if (!got)
            return null;

        var length = BinaryPrimitives.ReadUInt32LittleEndian(header);
        var payload = new byte[length];
        if (length == 0)
            return payload;

        var full = await ReadExactlyOrEofAsync(stream, payload, ct).ConfigureAwait(false);
        if (!full)
            throw new EndOfStreamException("Connection closed mid-frame.");

        return payload;
    }

    /// <summary>
    /// Fills <paramref name="buffer"/> completely. Returns false only if EOF arrives before any
    /// byte is read (clean between-frame close); throws if EOF arrives partway through the buffer.
    /// </summary>
    private static async Task<bool> ReadExactlyOrEofAsync(Stream stream, byte[] buffer, CancellationToken ct)
    {
        var offset = 0;
        while (offset < buffer.Length)
        {
            var n = await stream.ReadAsync(buffer.AsMemory(offset, buffer.Length - offset), ct)
                .ConfigureAwait(false);
            if (n == 0)
            {
                if (offset == 0)
                    return false;
                throw new EndOfStreamException("Connection closed mid-frame.");
            }
            offset += n;
        }
        return true;
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `dotnet test tests/WinSuperWhisper.Tests --filter "FullyQualifiedName~FrameProtocolTests"`
Expected: PASS - 6 tests passed.

- [ ] **Step 5: Commit**

```bash
git add src/WinSuperWhisper.Core/Daemon/FrameProtocol.cs tests/WinSuperWhisper.Tests/Daemon/FrameProtocolTests.cs
git commit -m "feat(core): add FrameProtocol length-prefixed wire format with READY/EXIT"
```

---

### Task 6: DaemonClient (IDaemonClient over TcpClient)

Implements `IDaemonClient` over `System.Net.Sockets.TcpClient`. `ConnectAsync` connects to the configured host/port (default `127.0.0.1:8765`) then **awaits a READY frame before returning** (the handshake gate that keeps the hotkey disarmed until the model is loaded). `TranscribeAsync` sends a WAV frame and reads the transcript frame. `ShutdownAsync` sends exactly the `[EXIT]` bytes and closes. A socket drop raises `Disconnected`. Tested against an in-process fake `TcpListener` on `127.0.0.1:0` speaking the wire format - no Python, no real daemon.

**Files:**

- Create: `src/WinSuperWhisper.Core/Daemon/DaemonClient.cs`
- Test: `tests/WinSuperWhisper.Tests/Daemon/FakeDaemonServer.cs`
- Test: `tests/WinSuperWhisper.Tests/Daemon/DaemonClientTests.cs`

- [ ] **Step 1: Write the failing test (fake server + client tests)**

`tests/WinSuperWhisper.Tests/Daemon/FakeDaemonServer.cs`

```csharp
using System;
using System.Net;
using System.Net.Sockets;
using System.Threading;
using System.Threading.Tasks;
using WinSuperWhisper.Core.Daemon;

namespace WinSuperWhisper.Tests.Daemon;

/// <summary>
/// In-process fake of the Python whisper daemon, speaking the exact wire format on a loopback
/// ephemeral port (127.0.0.1:0). No real daemon, no Python. The test controls when READY is sent
/// and how requests are answered.
/// </summary>
internal sealed class FakeDaemonServer : IAsyncDisposable
{
    private readonly TcpListener _listener;
    private readonly CancellationTokenSource _cts = new();
    private readonly TimeSpan _readyDelay;
    private readonly Func<byte[], string> _transcribe;
    private Task? _loop;

    public FakeDaemonServer(Func<byte[], string>? transcribe = null, TimeSpan? readyDelay = null)
    {
        _transcribe = transcribe ?? (_ => "default transcript");
        _readyDelay = readyDelay ?? TimeSpan.Zero;
        _listener = new TcpListener(IPAddress.Loopback, 0);
        _listener.Start();
    }

    public int Port => ((IPEndPoint)_listener.LocalEndpoint).Port;

    /// <summary>Set true once the server has received the [EXIT] frame.</summary>
    public bool ReceivedExit { get; private set; }

    public void Start() => _loop = Task.Run(AcceptLoopAsync);

    /// <summary>Stops accepting and drops any live connection - used to simulate a daemon crash.</summary>
    public void Drop()
    {
        _cts.Cancel();
        _listener.Stop();
    }

    private async Task AcceptLoopAsync()
    {
        try
        {
            using var client = await _listener.AcceptTcpClientAsync(_cts.Token);
            using var stream = client.GetStream();

            if (_readyDelay > TimeSpan.Zero)
                await Task.Delay(_readyDelay, _cts.Token);

            await FrameProtocol.WriteFrameAsync(stream, FrameProtocol.ReadyPayload, _cts.Token);

            while (!_cts.IsCancellationRequested)
            {
                var frame = await FrameProtocol.ReadFrameAsync(stream, _cts.Token);
                if (frame is null)
                    return; // client closed between frames

                if (IsExit(frame))
                {
                    ReceivedExit = true;
                    return;
                }

                var transcript = _transcribe(frame);
                var bytes = System.Text.Encoding.UTF8.GetBytes(transcript);
                await FrameProtocol.WriteFrameAsync(stream, bytes, _cts.Token);
            }
        }
        catch (OperationCanceledException) { }
        catch (ObjectDisposedException) { }
        catch (System.IO.IOException) { }
        catch (SocketException) { }
    }

    private static bool IsExit(byte[] p) =>
        p.Length == 6 && p[0] == (byte)'[' && p[1] == (byte)'E' && p[2] == (byte)'X' &&
        p[3] == (byte)'I' && p[4] == (byte)'T' && p[5] == (byte)']';

    public async ValueTask DisposeAsync()
    {
        _cts.Cancel();
        _listener.Stop();
        if (_loop is not null)
        {
            try { await _loop; } catch { /* best effort */ }
        }
        _cts.Dispose();
    }
}
```

`tests/WinSuperWhisper.Tests/Daemon/DaemonClientTests.cs`

```csharp
using System;
using System.Linq;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using WinSuperWhisper.Core.Daemon;
using Xunit;

namespace WinSuperWhisper.Tests.Daemon;

public class DaemonClientTests
{
    private static readonly byte[] FakeWav = Encoding.ASCII.GetBytes("RIFF....WAVEfake");

    [Fact]
    public async Task ConnectAsync_BlocksUntilReady_ThenReportsReady()
    {
        await using var server = new FakeDaemonServer(readyDelay: TimeSpan.FromMilliseconds(150));
        server.Start();
        await using var client = new DaemonClient("127.0.0.1", server.Port);

        Assert.False(client.IsReady);

        var connect = client.ConnectAsync(CancellationToken.None);
        // Still connecting while the server withholds READY.
        Assert.False(connect.IsCompleted);

        await connect;

        Assert.True(client.IsReady);
    }

    [Fact]
    public async Task TranscribeAsync_RoundTripsRequestAndResponse()
    {
        await using var server = new FakeDaemonServer(transcribe: wav =>
        {
            // The fake echoes back proof it received the exact WAV bytes.
            return wav.SequenceEqual(FakeWav) ? "hello world" : "WRONG-PAYLOAD";
        });
        server.Start();
        await using var client = new DaemonClient("127.0.0.1", server.Port);
        await client.ConnectAsync(CancellationToken.None);

        var transcript = await client.TranscribeAsync(FakeWav, CancellationToken.None);

        Assert.Equal("hello world", transcript);
    }

    [Fact]
    public async Task TranscribeAsync_EmptyTranscript_ReturnsEmptyString()
    {
        await using var server = new FakeDaemonServer(transcribe: _ => "");
        server.Start();
        await using var client = new DaemonClient("127.0.0.1", server.Port);
        await client.ConnectAsync(CancellationToken.None);

        var transcript = await client.TranscribeAsync(FakeWav, CancellationToken.None);

        Assert.Equal("", transcript);
    }

    [Fact]
    public async Task ShutdownAsync_SendsExactlyTheExitFrame()
    {
        await using var server = new FakeDaemonServer();
        server.Start();
        await using var client = new DaemonClient("127.0.0.1", server.Port);
        await client.ConnectAsync(CancellationToken.None);

        await client.ShutdownAsync();

        // Give the server loop a moment to observe the [EXIT] frame and return.
        var deadline = DateTime.UtcNow.AddSeconds(2);
        while (!server.ReceivedExit && DateTime.UtcNow < deadline)
            await Task.Delay(10);

        Assert.True(server.ReceivedExit);
        Assert.False(client.IsReady);
    }

    [Fact]
    public async Task ServerDrop_RaisesDisconnected_AndReconnectReWaitsForReady()
    {
        var server = new FakeDaemonServer();
        server.Start();
        await using var client = new DaemonClient("127.0.0.1", server.Port);
        await client.ConnectAsync(CancellationToken.None);

        var disconnected = new TaskCompletionSource();
        client.Disconnected += (_, _) => disconnected.TrySetResult();

        // Simulate the daemon crashing: drop the connection, then a transcribe must surface it.
        server.Drop();
        await server.DisposeAsync();

        await Assert.ThrowsAnyAsync<Exception>(() =>
            client.TranscribeAsync(FakeWav, CancellationToken.None));

        await disconnected.Task.WaitAsync(TimeSpan.FromSeconds(2));
        Assert.False(client.IsReady);

        // A fresh daemon comes up on a new port; reconnect re-gates on READY.
        await using var server2 = new FakeDaemonServer(transcribe: _ => "back online");
        server2.Start();
        await using var client2 = new DaemonClient("127.0.0.1", server2.Port);
        await client2.ConnectAsync(CancellationToken.None);
        Assert.True(client2.IsReady);
        Assert.Equal("back online", await client2.TranscribeAsync(FakeWav, CancellationToken.None));
    }

    [Fact]
    public void Constructor_DefaultsToLoopback8765()
    {
        using var client = new DaemonClient();
        Assert.Equal("127.0.0.1", client.Host);
        Assert.Equal(8765, client.Port);
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `dotnet test tests/WinSuperWhisper.Tests --filter "FullyQualifiedName~DaemonClientTests"`
Expected: FAIL - compile error, `The type or namespace name 'DaemonClient' could not be found`.

- [ ] **Step 3: Write minimal implementation**

`src/WinSuperWhisper.Core/Daemon/DaemonClient.cs`

```csharp
using System;
using System.IO;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using WinSuperWhisper.Core.Interfaces;

namespace WinSuperWhisper.Core.Daemon;

/// <summary>
/// Persistent-TCP client for the whisper daemon. Connects to 127.0.0.1:8765, awaits the READY
/// handshake before <see cref="ConnectAsync"/> completes, then exchanges 1:1 ordered
/// request/response frames. A socket drop sets <see cref="IsReady"/> false and raises
/// <see cref="Disconnected"/>; the App layer reconnects (which re-waits for READY).
/// </summary>
public sealed class DaemonClient : IDaemonClient
{
    public const string DefaultHost = "127.0.0.1";
    public const int DefaultPort = 8765;

    private readonly SemaphoreSlim _ioLock = new(1, 1);
    private TcpClient? _tcp;
    private NetworkStream? _stream;
    private bool _disconnectedRaised;

    public DaemonClient(string host = DefaultHost, int port = DefaultPort)
    {
        Host = host;
        Port = port;
    }

    public event EventHandler? Disconnected;

    public string Host { get; }
    public int Port { get; }
    public bool IsReady { get; private set; }

    public async Task ConnectAsync(CancellationToken ct)
    {
        IsReady = false;
        _disconnectedRaised = false;

        var tcp = new TcpClient { NoDelay = true };
        await tcp.ConnectAsync(Host, Port, ct).ConfigureAwait(false);
        var stream = tcp.GetStream();

        // Handshake gate: do not return until the daemon has sent READY.
        var first = await FrameProtocol.ReadFrameAsync(stream, ct).ConfigureAwait(false);
        if (first is null || !FrameProtocol.IsReady(first))
        {
            tcp.Dispose();
            throw new InvalidOperationException("Daemon did not send READY on connect.");
        }

        _tcp = tcp;
        _stream = stream;
        IsReady = true;
    }

    public async Task<string> TranscribeAsync(byte[] wavBytes, CancellationToken ct)
    {
        var stream = _stream
            ?? throw new InvalidOperationException("Not connected. Call ConnectAsync first.");

        await _ioLock.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            await FrameProtocol.WriteFrameAsync(stream, wavBytes, ct).ConfigureAwait(false);
            var response = await FrameProtocol.ReadFrameAsync(stream, ct).ConfigureAwait(false);
            if (response is null)
                throw new IOException("Daemon closed the connection without responding.");
            return Encoding.UTF8.GetString(response);
        }
        catch (Exception) when (!ct.IsCancellationRequested)
        {
            HandleDrop();
            throw;
        }
        finally
        {
            _ioLock.Release();
        }
    }

    public async Task ShutdownAsync()
    {
        var stream = _stream;
        IsReady = false;
        if (stream is not null)
        {
            try
            {
                await FrameProtocol.WriteFrameAsync(stream, FrameProtocol.ExitPayload, CancellationToken.None)
                    .ConfigureAwait(false);
            }
            catch
            {
                // Best effort - the daemon also self-terminates on connection drop.
            }
        }
        CloseTransport();
    }

    private void HandleDrop()
    {
        IsReady = false;
        CloseTransport();
        if (!_disconnectedRaised)
        {
            _disconnectedRaised = true;
            Disconnected?.Invoke(this, EventArgs.Empty);
        }
    }

    private void CloseTransport()
    {
        _stream?.Dispose();
        _tcp?.Dispose();
        _stream = null;
        _tcp = null;
    }

    public ValueTask DisposeAsync()
    {
        CloseTransport();
        _ioLock.Dispose();
        return ValueTask.CompletedTask;
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `dotnet test tests/WinSuperWhisper.Tests --filter "FullyQualifiedName~DaemonClientTests"`
Expected: PASS - 6 tests passed (READY gate, request/response, empty transcript, exact [EXIT], drop/reconnect, default endpoint).

- [ ] **Step 5: Commit**

```bash
git add src/WinSuperWhisper.Core/Daemon/DaemonClient.cs tests/WinSuperWhisper.Tests/Daemon/FakeDaemonServer.cs tests/WinSuperWhisper.Tests/Daemon/DaemonClientTests.cs
git commit -m "feat(core): add DaemonClient with READY handshake gate over TcpClient"
```

---

### Task 7: DictationOrchestrator (wires the five interfaces; full pipeline mocked)

The pure-logic conductor. It subscribes to `IHotkeyService` press/release, drives `IAudioCapture`, encodes via `WavEncoder`, calls `IDaemonClient.TranscribeAsync`, and injects via `ITextInjector` only on a non-empty transcript. Foreground capture is an injected seam (an `Action` the App layer fills with `GetForegroundWindow`/`SetForegroundWindow`; in Core it is just a callback so the orchestrator stays testable on Linux). `RecorderState` is exposed and walks `WarmingUp -> Idle -> Recording -> Transcribing -> Idle`. The hotkey is armed only after the daemon reports ready.

**Behavior encoded (from the spec's data flow):**

- Construction: state is `WarmingUp`, hotkey not armed.
- `OnDaemonReady()`: `SetArmed(true)`, state `Idle`.
- Hotkey `Pressed`: capture the foreground window (seam), `IAudioCapture.Start()`, state `Recording`.
- Hotkey `Released`: `IAudioCapture.Stop()`, state `Transcribing`, `GetCapturedPcm()` -> `WavEncoder.Encode` -> `TranscribeAsync`; non-empty -> restore foreground (seam) + `Inject(text)`; empty -> no injection; state back to `Idle`.
- A `Pressed` event while not armed is ignored (the gate).

**Files:**

- Create: `src/WinSuperWhisper.Core/Orchestrator/IForegroundWindow.cs`
- Create: `src/WinSuperWhisper.Core/Orchestrator/DictationOrchestrator.cs`
- Test: `tests/WinSuperWhisper.Tests/Orchestrator/DictationOrchestratorTests.cs`

- [ ] **Step 1: Write the failing test**

`tests/WinSuperWhisper.Tests/Orchestrator/DictationOrchestratorTests.cs`

```csharp
using System;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Moq;
using WinSuperWhisper.Core.Interfaces;
using WinSuperWhisper.Core.Models;
using WinSuperWhisper.Core.Orchestrator;
using Xunit;

namespace WinSuperWhisper.Tests.Orchestrator;

public class DictationOrchestratorTests
{
    private static readonly byte[] Pcm = { 1, 0, 2, 0, 3, 0, 4, 0 };

    private sealed class Harness
    {
        public Mock<IHotkeyService> Hotkey { get; } = new(MockBehavior.Loose);
        public Mock<IAudioCapture> Audio { get; } = new(MockBehavior.Loose);
        public Mock<ITextInjector> Injector { get; } = new(MockBehavior.Loose);
        public Mock<IDaemonClient> Daemon { get; } = new(MockBehavior.Loose);
        public Mock<IForegroundWindow> Foreground { get; } = new(MockBehavior.Loose);
        public DictationOrchestrator Orchestrator { get; }

        public Harness(string transcript)
        {
            Audio.Setup(a => a.GetCapturedPcm()).Returns(Pcm);
            Daemon.Setup(d => d.TranscribeAsync(It.IsAny<byte[]>(), It.IsAny<CancellationToken>()))
                  .ReturnsAsync(transcript);
            Foreground.Setup(f => f.Capture()).Returns(new IntPtr(4242));
            Injector.Setup(i => i.Inject(It.IsAny<string>())).Returns(InjectionResult.Typed);

            Orchestrator = new DictationOrchestrator(
                Hotkey.Object, Audio.Object, Injector.Object, Daemon.Object, Foreground.Object);
        }

        public void RaisePressed() => Hotkey.Raise(h => h.Pressed += null, EventArgs.Empty);
        public void RaiseReleased() => Hotkey.Raise(h => h.Released += null, EventArgs.Empty);
    }

    [Fact]
    public void StartsWarmingUp_AndDoesNotArmHotkey()
    {
        var h = new Harness("ignored");

        Assert.Equal(RecorderState.WarmingUp, h.Orchestrator.State);
        h.Hotkey.Verify(x => x.SetArmed(true), Times.Never);
    }

    [Fact]
    public void OnDaemonReady_ArmsHotkey_AndGoesIdle()
    {
        var h = new Harness("ignored");

        h.Orchestrator.OnDaemonReady();

        h.Hotkey.Verify(x => x.SetArmed(true), Times.Once);
        Assert.Equal(RecorderState.Idle, h.Orchestrator.State);
    }

    [Fact]
    public void Pressed_BeforeReady_IsIgnored()
    {
        var h = new Harness("ignored");
        h.Hotkey.SetupGet(x => x.IsArmed).Returns(false);

        h.RaisePressed();

        h.Audio.Verify(a => a.Start(), Times.Never);
        Assert.Equal(RecorderState.WarmingUp, h.Orchestrator.State);
    }

    [Fact]
    public void Pressed_WhenArmed_CapturesForegroundAndStartsRecording()
    {
        var h = new Harness("ignored");
        h.Orchestrator.OnDaemonReady();
        h.Hotkey.SetupGet(x => x.IsArmed).Returns(true);

        h.RaisePressed();

        h.Foreground.Verify(f => f.Capture(), Times.Once);
        h.Audio.Verify(a => a.Start(), Times.Once);
        Assert.Equal(RecorderState.Recording, h.Orchestrator.State);
    }

    [Fact]
    public async Task FullPipeline_NonEmptyTranscript_InjectsAndReturnsIdle()
    {
        var h = new Harness("hello captain");
        h.Orchestrator.OnDaemonReady();
        h.Hotkey.SetupGet(x => x.IsArmed).Returns(true);

        h.RaisePressed();
        await h.Orchestrator.ReleaseAsync(); // deterministic await of the release pipeline

        var seq = new MockSequence();
        h.Audio.Verify(a => a.Stop(), Times.Once);
        h.Audio.Verify(a => a.GetCapturedPcm(), Times.Once);
        h.Daemon.Verify(d => d.TranscribeAsync(
            It.Is<byte[]>(w => w.Length == 44 + Pcm.Length), It.IsAny<CancellationToken>()), Times.Once);
        h.Foreground.Verify(f => f.Restore(new IntPtr(4242)), Times.Once);
        h.Injector.Verify(i => i.Inject("hello captain"), Times.Once);
        Assert.Equal(RecorderState.Idle, h.Orchestrator.State);
    }

    [Fact]
    public async Task FullPipeline_EmptyTranscript_SkipsInjection()
    {
        var h = new Harness("");
        h.Orchestrator.OnDaemonReady();
        h.Hotkey.SetupGet(x => x.IsArmed).Returns(true);

        h.RaisePressed();
        await h.Orchestrator.ReleaseAsync();

        h.Daemon.Verify(d => d.TranscribeAsync(It.IsAny<byte[]>(), It.IsAny<CancellationToken>()), Times.Once);
        h.Injector.Verify(i => i.Inject(It.IsAny<string>()), Times.Never);
        Assert.Equal(RecorderState.Idle, h.Orchestrator.State);
    }

    [Fact]
    public async Task Released_Event_DrivesTheSamePipeline()
    {
        // The hotkey Released event, not just the direct ReleaseAsync call, runs the pipeline.
        var h = new Harness("via event");
        h.Orchestrator.OnDaemonReady();
        h.Hotkey.SetupGet(x => x.IsArmed).Returns(true);

        h.RaisePressed();
        h.RaiseReleased();

        // The event handler runs the async pipeline fire-and-forget; await its completion signal.
        await h.Orchestrator.WaitForIdleAsync(TimeSpan.FromSeconds(2));

        h.Injector.Verify(i => i.Inject("via event"), Times.Once);
        Assert.Equal(RecorderState.Idle, h.Orchestrator.State);
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `dotnet test tests/WinSuperWhisper.Tests --filter "FullyQualifiedName~DictationOrchestratorTests"`
Expected: FAIL - compile error, `The type or namespace name 'DictationOrchestrator' could not be found` (and `IForegroundWindow`).

- [ ] **Step 3: Write minimal implementation**

`src/WinSuperWhisper.Core/Orchestrator/IForegroundWindow.cs`

```csharp
using System;

namespace WinSuperWhisper.Core.Orchestrator;

/// <summary>
/// Seam over the Win32 foreground-window dance (GetForegroundWindow / SetForegroundWindow).
/// Lives in Core as an interface so the orchestrator is testable on Linux; the App project
/// supplies the real Win32 implementation. The handle is opaque to Core.
/// </summary>
public interface IForegroundWindow
{
    /// <summary>Capture the currently-focused window handle (on hotkey press).</summary>
    IntPtr Capture();

    /// <summary>Restore focus to a previously captured handle (before injecting).</summary>
    void Restore(IntPtr handle);
}
```

`src/WinSuperWhisper.Core/Orchestrator/DictationOrchestrator.cs`

```csharp
using System;
using System.Threading;
using System.Threading.Tasks;
using WinSuperWhisper.Core.Audio;
using WinSuperWhisper.Core.Interfaces;
using WinSuperWhisper.Core.Models;

namespace WinSuperWhisper.Core.Orchestrator;

/// <summary>
/// Wires the five Windows-hiding interfaces into the hold-to-record dictation pipeline.
/// Pure logic: it owns the <see cref="RecorderState"/> machine and the call sequencing, but
/// every Windows API is behind an injected interface, so the whole flow is testable on Linux.
/// </summary>
public sealed class DictationOrchestrator
{
    private readonly IHotkeyService _hotkey;
    private readonly IAudioCapture _audio;
    private readonly ITextInjector _injector;
    private readonly IDaemonClient _daemon;
    private readonly IForegroundWindow _foreground;

    private IntPtr _capturedWindow;
    private volatile TaskCompletionSource _idleSignal =
        new(TaskCreationOptions.RunContinuationsAsynchronously);

    public DictationOrchestrator(
        IHotkeyService hotkey,
        IAudioCapture audio,
        ITextInjector injector,
        IDaemonClient daemon,
        IForegroundWindow foreground)
    {
        _hotkey = hotkey;
        _audio = audio;
        _injector = injector;
        _daemon = daemon;
        _foreground = foreground;

        State = RecorderState.WarmingUp;

        _hotkey.Pressed += OnPressed;
        _hotkey.Released += OnReleased;
    }

    public RecorderState State { get; private set; }

    /// <summary>Called when the daemon's READY handshake completes: arm the hotkey and go idle.</summary>
    public void OnDaemonReady()
    {
        _hotkey.SetArmed(true);
        State = RecorderState.Idle;
    }

    private void OnPressed(object? sender, EventArgs e)
    {
        if (!_hotkey.IsArmed || State != RecorderState.Idle)
            return;

        _capturedWindow = _foreground.Capture();
        _audio.Start();
        State = RecorderState.Recording;
    }

    private void OnReleased(object? sender, EventArgs e)
    {
        // Fire-and-forget the async pipeline; tests await WaitForIdleAsync for determinism.
        _ = ReleaseAsync();
    }

    /// <summary>
    /// The release pipeline: stop capture, transcribe, inject on non-empty result, return to idle.
    /// Exposed so tests can await it deterministically.
    /// </summary>
    public async Task ReleaseAsync()
    {
        if (State != RecorderState.Recording)
            return;

        _audio.Stop();
        State = RecorderState.Transcribing;

        try
        {
            var pcm = _audio.GetCapturedPcm();
            var wav = WavEncoder.Encode(pcm);
            var transcript = await _daemon.TranscribeAsync(wav, CancellationToken.None)
                .ConfigureAwait(false);

            if (!string.IsNullOrEmpty(transcript))
            {
                _foreground.Restore(_capturedWindow);
                _injector.Inject(transcript);
            }
        }
        finally
        {
            State = RecorderState.Idle;
            SignalIdle();
        }
    }

    /// <summary>Awaitable that completes the next time the pipeline returns to Idle.</summary>
    public Task WaitForIdleAsync(TimeSpan timeout) => _idleSignal.Task.WaitAsync(timeout);

    private void SignalIdle()
    {
        var prev = Interlocked.Exchange(
            ref _idleSignal, new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously));
        prev.TrySetResult();
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `dotnet test tests/WinSuperWhisper.Tests --filter "FullyQualifiedName~DictationOrchestratorTests"`
Expected: PASS - 7 tests passed (warming up, arm on ready, gate before ready, record on press, full pipeline with injection, empty-transcript skip, Released-event drives pipeline).

- [ ] **Step 5: Commit**

```bash
git add src/WinSuperWhisper.Core/Orchestrator tests/WinSuperWhisper.Tests/Orchestrator/DictationOrchestratorTests.cs
git commit -m "feat(core): add DictationOrchestrator wiring the dictation pipeline"
```

---

### Task 8: Full Core suite green in Podman + portability guard

Confirm the entire Core suite passes together in the container and that Core has not pulled in any Windows-only dependency (the Podman boundary).

**Files:**

- (no new source)

- [ ] **Step 1: Run the entire Core suite in Podman**

Run:

```bash
podman run --rm -t -v "$PWD":/work:Z -w /work \
  mcr.microsoft.com/dotnet/sdk:8.0 \
  dotnet test tests/WinSuperWhisper.Tests
```

Expected: PASS - all tests across `HotkeyComboTests`, `InterfaceShapeTests`, `AppConfigStoreTests`, `WavEncoderTests`, `FrameProtocolTests`, `DaemonClientTests`, and `DictationOrchestratorTests` pass; `Failed: 0`.

- [ ] **Step 2: Verify the Core library targets net8.0 only (no Windows TFM, no WPF/NAudio)**

Run:

```bash
podman run --rm -t -v "$PWD":/work:Z -w /work \
  mcr.microsoft.com/dotnet/sdk:8.0 \
  bash -lc 'grep -E "net8.0-windows|PresentationFramework|PresentationCore|WindowsBase|NAudio" src/WinSuperWhisper.Core/WinSuperWhisper.Core.csproj && echo "LEAK" || echo "CLEAN"'
```

Expected: prints `CLEAN` (no Windows TFM and no WPF/NAudio reference leaked into Core). If it prints `LEAK`, stop and escalate - a Windows dependency in Core breaks the Podman boundary and is a design violation, not something to patch around.

- [ ] **Step 3: Commit (only if the prior tasks left anything uncommitted, e.g. a doc note)**

If everything was already committed task-by-task, there is nothing to commit here and this step is a no-op. Otherwise:

```bash
git add -A
git commit -m "test(core): full Core suite green in Podman"
```

---

## Self-review (run before declaring this plan done)

**Spec coverage.** Every Core requirement from the spec's Phase 1 list and the contract is mapped:

- Five interfaces in Core - Task 2.
- All models incl. `AppConfig` - Task 1.
- Config persistence to `%APPDATA%\WinSuperWhisper\config.json` (injected path) - Task 3.
- WAV encoding (PCM in, WAV bytes out) - Task 4.
- IPC wire format / framing / READY / EXIT - Task 5.
- Daemon client: handshake gate, request/response, EXIT, reconnect/disconnect - Task 6.
- Orchestrator wiring all components; empty transcript skips injection; hotkey gated until ready - Task 7.

**Type consistency.** `DaemonClient.IsReady` (not `Ready`), `IsCapturing`, `GetCapturedPcm`, `Inject`, `SetArmed`, `IsArmed`, `Capture`/`Restore` on `IForegroundWindow`, `WavEncoder.Encode`, `FrameProtocol.ReadyPayload`/`ExitPayload`/`IsReady`/`WriteFrameAsync`/`ReadFrameAsync`, `RecorderState` values `Idle/WarmingUp/Recording/Transcribing` - all used identically across tasks and matching the contract verbatim.

**Placeholder scan.** No TBD/TODO/"handle edge cases"/"similar to Task N". Every code step is complete and compiling under nullable-enabled `net8.0`.

---

## Exit conditions (all must be green)

- [ ] All five interfaces (`IHotkeyService`, `IAudioCapture`, `ITextInjector`, `IMonitorService`, `IDaemonClient`) and all six models (`HotkeyCombo`, `MonitorInfo`, `AudioLevel`, `InjectionResult`, `RecorderState`, `AppConfig`) compile in `WinSuperWhisper.Core`.
- [ ] xUnit suite is green in Podman for: `AppConfigStore` round-trip, `WavEncoder` (header + data subchunk + empty-PCM), `FrameProtocol` (frame round-trip + READY + EXIT), `DaemonClient`, and `DictationOrchestrator`.
- [ ] The IPC-client tests cover the **READY handshake gate** (ConnectAsync blocks until READY, then completes), **request/response round-trip**, **reconnect / `Disconnected` on server drop**, and **exact `[EXIT]` bytes** sent on shutdown - all against an in-process fake `TcpListener`, no Python, no real daemon.
- [ ] The orchestrator test asserts the full call sequence with all interfaces mocked, that an **empty transcript skips injection**, and that the **hotkey is gated until ready**.
- [ ] `WinSuperWhisper.Core.csproj` shows `CLEAN` against the WPF/NAudio/`net8.0-windows` grep (the Podman boundary holds).
- [ ] `dotnet test tests/WinSuperWhisper.Tests` reports `Failed: 0` inside the Podman container.

**Dependencies:** this file depends on `01-foundation` (repo, solution, Core + Tests projects must already build) and **runs in parallel with `02b-daemon`** (the Python side of the same wire format; no shared code).
