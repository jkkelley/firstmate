# WinSuperWhisper Phase 1 - 01 Foundation ("Slab") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Tag: PODMAN** - every task in this file is verifiable on Linux (no Windows machine required). The `.App` / `.App.Tests` projects (`net8.0-windows`) are _created_ here but are not built on Linux; only `WinSuperWhisper.Core` and `WinSuperWhisper.Tests` are compiled and tested in the Podman tier.

**Goal:** Stand up the standalone `WinSuperWhisper` git repo with a `WinSuperWhisper.sln`, four projects with the exact target frameworks, wired project references, the xUnit+Moq test harness, a .NET `.gitignore`, the dual-tier `run-tests.sh` automation, and the load-bearing guardrail that proves `WinSuperWhisper.Core` carries no WPF/NAudio dependency and compiles on Linux.

**Architecture:** A strict two-assembly split is the whole point of the foundation. `WinSuperWhisper.Core` (`net8.0`) holds portable logic and compiles in Podman; `WinSuperWhisper.App` (`net8.0-windows`) holds WPF + Win32 + NAudio and only ever builds on Windows. The split is enforced mechanically - if any WPF/NAudio type leaks into Core, the Linux `dotnet build` of Core breaks immediately. Tests are tiered to match: Core + Python in Podman (Tier 1), Win32/UI on Windows via `powershell.exe` (Tier 2).

**Tech Stack:** .NET 8 SDK, C#, xUnit, Moq, bash, PowerShell, Podman (dotnet SDK container on Linux). The authoritative design spec lives at `/home/luna/projects/firstmate/docs/superpowers/specs/2026-06-22-winsuperwhisper-design.md` and the shared Phase 1 contract is authoritative for all names, signatures, the file tree, and conventions.

---

## Scope of this file

This file ("Foundation" / "Slab") covers ONLY:

1. Initialize the standalone git repo `WinSuperWhisper` (NOT inside firstmate; default branch `main`).
2. Create `WinSuperWhisper.sln` and the four projects with the EXACT TFMs from the contract:
   - `src/WinSuperWhisper.Core` -> `net8.0`
   - `src/WinSuperWhisper.App` -> `net8.0-windows`
   - `tests/WinSuperWhisper.Tests` -> `net8.0`
   - `tests/WinSuperWhisper.App.Tests` -> `net8.0-windows`
3. Wire project references: `Tests -> Core`, `App -> Core`, `App.Tests -> App`.
4. Add xUnit + Moq to both test projects; add a `.gitignore` for .NET.
5. The critical guardrail: a test that proves Core does NOT reference WPF/NAudio and compiles on Linux (placeholder failing xUnit test in `WinSuperWhisper.Tests` proven red in Podman, then green).
6. Write `scripts/run-tests.sh` (dual-tier) and `scripts/win-tests.ps1`, with `FM_SKIP_WIN=1` behavior.

It does NOT implement any interface, model, the daemon, adapters, or UI. Those land in `02a-core`, `02b-daemon`, `03-adapters`, `04-ui`, `05-movein`.

---

## Escalation contract (read once, applies to the whole file)

- **Exit conditions are binary.** Every "Expected:" line below is a gate. Either the command produces the stated output (green) or it does not (not green). There is no partial credit and no "looks close enough".
- **Never weaken a test or a gate to make it pass.** If a gate cannot be made green honestly, that is a judgment call - STOP and escalate.
- **Mechanical failures get a bounded 2-attempt retry.** A transient container pull, a flaky network fetch of a NuGet package, a first-run SDK warm-up: retry at most twice. If it still fails after the second attempt, escalate with the exact command and the exact error output.
- **Judgment calls escalate immediately - do not retry, do not guess.** This includes: any ambiguity in the spec or contract, a missing tool or credential, the Windows machine being unavailable when a WIN11 step needs it (none in this file, but the principle holds), or any temptation to relax a gate.
- **Never commit a red tree.** One commit per unit, only after its PASS gate is green, with the exact conventional-commit message given.

---

## Podman invocation pattern (how `dotnet` runs on Linux here)

There is no host .NET SDK assumption. Every `dotnet` command in this file runs inside a pinned .NET 8 SDK container via Podman, with the repo bind-mounted and a persistent NuGet cache so package restore is not re-downloaded every task. Use this exact wrapper.

`scripts/dotnet.sh` (created in Task 0 below) is the single entry point:

```bash
#!/usr/bin/env bash
# Runs `dotnet` inside a pinned .NET 8 SDK container via Podman.
# The repo root is bind-mounted at /work; NuGet packages are cached in a named volume
# so restores persist across invocations. All args are passed through to `dotnet`.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="mcr.microsoft.com/dotnet/sdk:8.0"

podman run --rm \
  -v "${REPO_ROOT}:/work:Z" \
  -v wsw-nuget:/root/.nuget/packages \
  -w /work \
  -e DOTNET_CLI_TELEMETRY_OPTOUT=1 \
  -e DOTNET_NOLOGO=1 \
  "${IMAGE}" \
  dotnet "$@"
```

So `scripts/dotnet.sh build src/WinSuperWhisper.Core` means "run `dotnet build src/WinSuperWhisper.Core` inside the SDK container". Everywhere below, `scripts/dotnet.sh <args>` is the literal command to run; it is equivalent to invoking `dotnet <args>` on a host SDK if one happens to be installed, but the container form is the supported path on this Linux host.

> If `podman` itself is missing, that is a judgment call (missing tool) - escalate per the contract; do not silently fall back to a host SDK.

---

### Task 0: Repo, gitignore, and the Podman dotnet wrapper

**Files:**

- Create: `WinSuperWhisper/.gitignore`
- Create: `WinSuperWhisper/scripts/dotnet.sh`

> All paths below are relative to the standalone `WinSuperWhisper/` repo root. This repo is created fresh and is NOT a subdirectory of firstmate; pick any working location outside the firstmate tree.

- [ ] **Step 1: Verify the repo does not yet exist (the "red" state)**

Run:

```bash
test -d WinSuperWhisper/.git && echo "EXISTS" || echo "ABSENT"
```

Expected: `ABSENT`

- [ ] **Step 2: Initialize the repo with `main` as the default branch**

Run:

```bash
mkdir -p WinSuperWhisper && cd WinSuperWhisper && git init -b main
```

Expected: `Initialized empty Git repository in .../WinSuperWhisper/.git/`

- [ ] **Step 3: Create the .NET `.gitignore`**

Create `.gitignore`:

```gitignore
# Build output
[Bb]in/
[Oo]bj/
[Oo]ut/
artifacts/

# .NET / Rider / VS
.vs/
.vscode/
*.user
*.suo
*.userosscache
*.sln.docstates
project.lock.json
*.nupkg
*.snupkg

# Test results
[Tt]est[Rr]esult*/
*.trx
coverage*.json
coverage*.xml
*.coverage

# Python (wsl daemon)
__pycache__/
*.py[cod]
.pytest_cache/
.venv/
venv/

# OS cruft
.DS_Store
Thumbs.db

# Local container/NuGet scratch
*.binlog
```

- [ ] **Step 4: Create the Podman dotnet wrapper**

Create `scripts/dotnet.sh` with exactly the content shown in the "Podman invocation pattern" section above, then make it executable:

```bash
mkdir -p scripts
# write scripts/dotnet.sh (content from the Podman invocation pattern section)
chmod +x scripts/dotnet.sh
```

- [ ] **Step 5: Verify the wrapper reaches a working SDK (the "green" state)**

Run:

```bash
scripts/dotnet.sh --version
```

Expected: a line starting with `8.0.` (e.g. `8.0.x`). A first-run image pull is a mechanical step; allow the bounded retry if the pull is interrupted.

- [ ] **Step 6: Commit**

```bash
git add .gitignore scripts/dotnet.sh
git commit -m "chore: init repo with .NET gitignore and Podman dotnet wrapper"
```

---

### Task 1: Solution + WinSuperWhisper.Core (net8.0)

**Files:**

- Create: `WinSuperWhisper.sln`
- Create: `src/WinSuperWhisper.Core/WinSuperWhisper.Core.csproj`

- [ ] **Step 1: Verify there is nothing to build yet (the "red" state)**

Run:

```bash
scripts/dotnet.sh build src/WinSuperWhisper.Core
```

Expected: FAIL - a "Specified project or solution file ... does not exist" / MSBUILD project-not-found error (the project does not exist yet).

- [ ] **Step 2: Create the solution and the Core project**

Run:

```bash
scripts/dotnet.sh new sln -n WinSuperWhisper
scripts/dotnet.sh new classlib -n WinSuperWhisper.Core -o src/WinSuperWhisper.Core
```

- [ ] **Step 3: Replace the generated Core csproj with the exact contract content**

`dotnet new classlib` emits a placeholder `Class1.cs` and a default csproj. Delete the placeholder and pin the csproj exactly:

```bash
rm -f src/WinSuperWhisper.Core/Class1.cs
```

Overwrite `src/WinSuperWhisper.Core/WinSuperWhisper.Core.csproj`:

```xml
<Project Sdk="Microsoft.NET.Sdk">

  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <ImplicitUsings>enable</ImplicitUsings>
    <Nullable>enable</Nullable>
    <RootNamespace>WinSuperWhisper.Core</RootNamespace>
    <AssemblyName>WinSuperWhisper.Core</AssemblyName>
  </PropertyGroup>

</Project>
```

- [ ] **Step 4: Add the Core project to the solution**

Run:

```bash
scripts/dotnet.sh sln WinSuperWhisper.sln add src/WinSuperWhisper.Core/WinSuperWhisper.Core.csproj
```

- [ ] **Step 5: Verify Core builds on Linux (the "green" state)**

Run:

```bash
scripts/dotnet.sh build src/WinSuperWhisper.Core
```

Expected: `Build succeeded.` with `0 Error(s)`.

- [ ] **Step 6: Commit**

```bash
git add WinSuperWhisper.sln src/WinSuperWhisper.Core
git commit -m "feat: add solution and WinSuperWhisper.Core (net8.0) library"
```

---

### Task 2: WinSuperWhisper.App (net8.0-windows), App -> Core reference

**Files:**

- Create: `src/WinSuperWhisper.App/WinSuperWhisper.App.csproj`

> The App project targets `net8.0-windows` and uses WPF, so it does NOT build on this Linux host. That is expected and correct - it is created and referenced here, and is built only in the Windows tier (later phases). The Podman gate for this task is limited to: the solution still restores/lists, and Core still builds.

- [ ] **Step 1: Verify the App project is not yet on the solution (the "red" state)**

Run:

```bash
scripts/dotnet.sh sln WinSuperWhisper.sln list
```

Expected: lists only `src/WinSuperWhisper.Core/WinSuperWhisper.Core.csproj` (App absent).

- [ ] **Step 2: Create the App project directory and csproj**

Run:

```bash
mkdir -p src/WinSuperWhisper.App
```

Create `src/WinSuperWhisper.App/WinSuperWhisper.App.csproj`:

```xml
<Project Sdk="Microsoft.NET.Sdk">

  <PropertyGroup>
    <OutputType>WinExe</OutputType>
    <TargetFramework>net8.0-windows</TargetFramework>
    <UseWPF>true</UseWPF>
    <ImplicitUsings>enable</ImplicitUsings>
    <Nullable>enable</Nullable>
    <RootNamespace>WinSuperWhisper.App</RootNamespace>
    <AssemblyName>WinSuperWhisper.App</AssemblyName>
  </PropertyGroup>

  <ItemGroup>
    <PackageReference Include="NAudio" Version="2.2.1" />
  </ItemGroup>

  <ItemGroup>
    <ProjectReference Include="..\WinSuperWhisper.Core\WinSuperWhisper.Core.csproj" />
  </ItemGroup>

</Project>
```

- [ ] **Step 3: Add the App project to the solution**

Run:

```bash
scripts/dotnet.sh sln WinSuperWhisper.sln add src/WinSuperWhisper.App/WinSuperWhisper.App.csproj
```

- [ ] **Step 4: Verify the App is on the solution and Core still builds (the "green" state)**

Run:

```bash
scripts/dotnet.sh sln WinSuperWhisper.sln list
```

Expected: lists both `src/WinSuperWhisper.Core/...` and `src/WinSuperWhisper.App/...`.

Run:

```bash
scripts/dotnet.sh build src/WinSuperWhisper.Core
```

Expected: `Build succeeded.` with `0 Error(s)` (Core is unaffected by adding App).

> Do NOT run `scripts/dotnet.sh build src/WinSuperWhisper.App` on Linux - `net8.0-windows` + WPF will not restore/build here. That build belongs to the Windows tier.

- [ ] **Step 5: Commit**

```bash
git add src/WinSuperWhisper.App WinSuperWhisper.sln
git commit -m "feat: add WinSuperWhisper.App (net8.0-windows, WPF+NAudio) referencing Core"
```

---

### Task 3: WinSuperWhisper.Tests (net8.0, xUnit+Moq), Tests -> Core

**Files:**

- Create: `tests/WinSuperWhisper.Tests/WinSuperWhisper.Tests.csproj`

- [ ] **Step 1: Verify the test project does not yet exist (the "red" state)**

Run:

```bash
scripts/dotnet.sh test tests/WinSuperWhisper.Tests
```

Expected: FAIL - "Specified project or solution file ... does not exist" (project absent).

- [ ] **Step 2: Create the xUnit test project**

Run:

```bash
scripts/dotnet.sh new xunit -n WinSuperWhisper.Tests -o tests/WinSuperWhisper.Tests
rm -f tests/WinSuperWhisper.Tests/UnitTest1.cs
```

- [ ] **Step 3: Pin the test csproj with the exact TFM and references**

Overwrite `tests/WinSuperWhisper.Tests/WinSuperWhisper.Tests.csproj`:

```xml
<Project Sdk="Microsoft.NET.Sdk">

  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <ImplicitUsings>enable</ImplicitUsings>
    <Nullable>enable</Nullable>
    <IsPackable>false</IsPackable>
    <RootNamespace>WinSuperWhisper.Tests</RootNamespace>
  </PropertyGroup>

  <ItemGroup>
    <PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.11.1" />
    <PackageReference Include="xunit" Version="2.9.2" />
    <PackageReference Include="xunit.runner.visualstudio" Version="2.8.2">
      <IncludeAssets>runtime; build; native; contentfiles; analyzers; buildtransitive</IncludeAssets>
      <PrivateAssets>all</PrivateAssets>
    </PackageReference>
    <PackageReference Include="Moq" Version="4.20.72" />
  </ItemGroup>

  <ItemGroup>
    <ProjectReference Include="..\..\src\WinSuperWhisper.Core\WinSuperWhisper.Core.csproj" />
  </ItemGroup>

</Project>
```

- [ ] **Step 4: Add the test project to the solution**

Run:

```bash
scripts/dotnet.sh sln WinSuperWhisper.sln add tests/WinSuperWhisper.Tests/WinSuperWhisper.Tests.csproj
```

- [ ] **Step 5: Verify the empty test project builds and runs zero tests (the "green" state)**

Run:

```bash
scripts/dotnet.sh test tests/WinSuperWhisper.Tests
```

Expected: `Build succeeded.` then a passing run with `Passed!  - Failed: 0, Passed: 0` (no tests yet, but the harness compiles and references Core + Moq). A first-run NuGet restore of xUnit/Moq is a mechanical step; allow the bounded retry on a transient fetch failure.

- [ ] **Step 6: Commit**

```bash
git add tests/WinSuperWhisper.Tests WinSuperWhisper.sln
git commit -m "test: add WinSuperWhisper.Tests (net8.0 xUnit+Moq) referencing Core"
```

---

### Task 4: WinSuperWhisper.App.Tests (net8.0-windows, xUnit+Moq), App.Tests -> App

**Files:**

- Create: `tests/WinSuperWhisper.App.Tests/WinSuperWhisper.App.Tests.csproj`

> Like `WinSuperWhisper.App`, this project is `net8.0-windows` and is NOT built on Linux. It is created, referenced, and added to the solution here; its tests run only in the Windows tier.

- [ ] **Step 1: Verify the App.Tests project is not yet on the solution (the "red" state)**

Run:

```bash
scripts/dotnet.sh sln WinSuperWhisper.sln list
```

Expected: lists Core, App, and Tests, but NOT `tests/WinSuperWhisper.App.Tests/...`.

- [ ] **Step 2: Create the App.Tests directory and csproj**

Run:

```bash
mkdir -p tests/WinSuperWhisper.App.Tests
```

Create `tests/WinSuperWhisper.App.Tests/WinSuperWhisper.App.Tests.csproj`:

```xml
<Project Sdk="Microsoft.NET.Sdk">

  <PropertyGroup>
    <TargetFramework>net8.0-windows</TargetFramework>
    <UseWPF>true</UseWPF>
    <ImplicitUsings>enable</ImplicitUsings>
    <Nullable>enable</Nullable>
    <IsPackable>false</IsPackable>
    <RootNamespace>WinSuperWhisper.App.Tests</RootNamespace>
  </PropertyGroup>

  <ItemGroup>
    <PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.11.1" />
    <PackageReference Include="xunit" Version="2.9.2" />
    <PackageReference Include="xunit.runner.visualstudio" Version="2.8.2">
      <IncludeAssets>runtime; build; native; contentfiles; analyzers; buildtransitive</IncludeAssets>
      <PrivateAssets>all</PrivateAssets>
    </PackageReference>
    <PackageReference Include="Moq" Version="4.20.72" />
  </ItemGroup>

  <ItemGroup>
    <ProjectReference Include="..\..\src\WinSuperWhisper.App\WinSuperWhisper.App.csproj" />
  </ItemGroup>

</Project>
```

- [ ] **Step 3: Add the App.Tests project to the solution**

Run:

```bash
scripts/dotnet.sh sln WinSuperWhisper.sln add tests/WinSuperWhisper.App.Tests/WinSuperWhisper.App.Tests.csproj
```

- [ ] **Step 4: Verify all four projects are on the solution (the "green" state)**

Run:

```bash
scripts/dotnet.sh sln WinSuperWhisper.sln list
```

Expected: lists exactly these four, with these exact relative paths:

```
src/WinSuperWhisper.Core/WinSuperWhisper.Core.csproj
src/WinSuperWhisper.App/WinSuperWhisper.App.csproj
tests/WinSuperWhisper.Tests/WinSuperWhisper.Tests.csproj
tests/WinSuperWhisper.App.Tests/WinSuperWhisper.App.Tests.csproj
```

Run (Core must still build clean on Linux):

```bash
scripts/dotnet.sh build src/WinSuperWhisper.Core
```

Expected: `Build succeeded.` with `0 Error(s)`.

> Do NOT build `WinSuperWhisper.App.Tests` on Linux - `net8.0-windows` belongs to the Windows tier.

- [ ] **Step 5: Commit**

```bash
git add tests/WinSuperWhisper.App.Tests WinSuperWhisper.sln
git commit -m "test: add WinSuperWhisper.App.Tests (net8.0-windows xUnit+Moq) referencing App"
```

---

### Task 5: The guardrail test - Core carries no WPF/NAudio and compiles on Linux

This is the load-bearing task of the foundation. The project split is only real if it is mechanically enforced. We do this in two moves: first a deliberately failing placeholder test to prove the Podman harness actually runs and _can_ go red, then the real guardrail assertion that the Core assembly's referenced assemblies include no WPF or NAudio names.

**Files:**

- Create: `tests/WinSuperWhisper.Tests/GuardrailTests.cs`

- [ ] **Step 1: Write a deliberately failing placeholder test (prove the harness can go red)**

Create `tests/WinSuperWhisper.Tests/GuardrailTests.cs`:

```csharp
using System.Linq;
using System.Reflection;
using Xunit;

namespace WinSuperWhisper.Tests;

public class GuardrailTests
{
    // Step 1 placeholder: deliberately failing, to prove the Podman test harness
    // actually runs assertions and reports red. Replaced in Step 3 by the real guardrail.
    [Fact]
    public void Harness_RunsAndCanFail()
    {
        Assert.True(false, "placeholder: proving the Podman harness reports failures");
    }
}
```

- [ ] **Step 2: Run it in Podman and verify it FAILS (the "red" state)**

Run:

```bash
scripts/dotnet.sh test tests/WinSuperWhisper.Tests --filter "FullyQualifiedName~GuardrailTests"
```

Expected: FAIL - `Failed: 1, Passed: 0`, with the message `placeholder: proving the Podman harness reports failures`. This proves the container-based test runner executes and can report a red test.

- [ ] **Step 3: Replace the placeholder with the real guardrail assertions**

The Core assembly is reachable through any Core type. Since no Core types exist yet (they arrive in `02a-core`), we assert against the loaded `WinSuperWhisper.Core` assembly itself via its name, plus a compile-time guard: the `WinSuperWhisper.Tests` project references Core only, so if WPF/NAudio had leaked into Core, restoring/building Core here would already have failed. The runtime assertion below adds defense in depth by scanning Core's referenced assemblies.

Overwrite `tests/WinSuperWhisper.Tests/GuardrailTests.cs`:

```csharp
using System;
using System.Linq;
using System.Reflection;
using Xunit;

namespace WinSuperWhisper.Tests;

public class GuardrailTests
{
    // Banned assembly name fragments. If any of these appear among WinSuperWhisper.Core's
    // referenced assemblies, the net8.0 / Linux / Podman boundary has been violated.
    private static readonly string[] BannedReferenceFragments =
    {
        "PresentationFramework",
        "PresentationCore",
        "WindowsBase",
        "NAudio",
    };

    private static Assembly LoadCoreAssembly()
    {
        // Core has no public types yet (they arrive in 02a-core), so load it by name.
        // The Tests project references Core, so the assembly is copied next to the test output.
        return Assembly.Load(new AssemblyName("WinSuperWhisper.Core"));
    }

    [Fact]
    public void Core_AssemblyLoadsOnLinux()
    {
        var core = LoadCoreAssembly();
        Assert.Equal("WinSuperWhisper.Core", core.GetName().Name);
    }

    [Fact]
    public void Core_DoesNotReferenceWpfOrNAudio()
    {
        var core = LoadCoreAssembly();
        var referenced = core.GetReferencedAssemblies()
            .Select(a => a.Name ?? string.Empty)
            .ToArray();

        foreach (var banned in BannedReferenceFragments)
        {
            Assert.DoesNotContain(
                referenced,
                name => name.Contains(banned, StringComparison.OrdinalIgnoreCase));
        }
    }
}
```

- [ ] **Step 4: Run the guardrail in Podman and verify it PASSES (the "green" state)**

Run:

```bash
scripts/dotnet.sh test tests/WinSuperWhisper.Tests --filter "FullyQualifiedName~GuardrailTests"
```

Expected: PASS - `Passed!  - Failed: 0, Passed: 2`. Both `Core_AssemblyLoadsOnLinux` and `Core_DoesNotReferenceWpfOrNAudio` are green, proving Core loads on Linux and pulls in no WPF/NAudio assembly.

> Honesty gate: if `Core_DoesNotReferenceWpfOrNAudio` ever fails in a later phase, that is the guardrail firing correctly - do NOT add the banned reference to Core to silence it, and do NOT delete the assertion. Move the offending code to `WinSuperWhisper.App` and escalate if the placement is ambiguous.

- [ ] **Step 5: Commit**

```bash
git add tests/WinSuperWhisper.Tests/GuardrailTests.cs
git commit -m "test: guardrail proving Core has no WPF/NAudio deps and loads on Linux"
```

---

### Task 6: scripts/win-tests.ps1 - the Windows test tier runner

**Files:**

- Create: `scripts/win-tests.ps1`

> This script runs the `net8.0-windows` test projects on the Windows side. It is invoked by `run-tests.sh` via `powershell.exe` from WSL. On this Linux host we only verify the file exists and is syntactically well-formed bash-callable (we do NOT execute PowerShell here). Its real exercise is the Windows tier in later phases.

- [ ] **Step 1: Verify the script does not yet exist (the "red" state)**

Run:

```bash
test -f scripts/win-tests.ps1 && echo "EXISTS" || echo "ABSENT"
```

Expected: `ABSENT`

- [ ] **Step 2: Create the PowerShell Windows-tier runner**

Create `scripts/win-tests.ps1`:

```powershell
#Requires -Version 5.1
<#
.SYNOPSIS
  Windows test tier for WinSuperWhisper. Runs the net8.0-windows test projects on a real
  Windows machine. Invoked by scripts/run-tests.sh via powershell.exe from WSL.
.DESCRIPTION
  Builds and tests the Windows-only projects (App + App.Tests). Exits non-zero on any failure
  so the calling run-tests.sh can fail the whole suite. No interactive prompts.
#>

$ErrorActionPreference = 'Stop'

# Resolve repo root: this script lives in <repo>\scripts\win-tests.ps1
$RepoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "== WinSuperWhisper Windows test tier =="
Write-Host "Repo root: $RepoRoot"

Push-Location $RepoRoot
try {
    # Build the Windows-only App project first (fast failure if WPF/Win32 won't compile).
    Write-Host "-- dotnet build src\WinSuperWhisper.App --"
    dotnet build "src\WinSuperWhisper.App\WinSuperWhisper.App.csproj" -c Debug
    if ($LASTEXITCODE -ne 0) { throw "App build failed (exit $LASTEXITCODE)" }

    # Run the Windows-only test project.
    Write-Host "-- dotnet test tests\WinSuperWhisper.App.Tests --"
    dotnet test "tests\WinSuperWhisper.App.Tests\WinSuperWhisper.App.Tests.csproj" -c Debug
    if ($LASTEXITCODE -ne 0) { throw "App.Tests failed (exit $LASTEXITCODE)" }

    Write-Host "== Windows test tier PASSED =="
    exit 0
}
catch {
    Write-Host "== Windows test tier FAILED: $_ =="
    exit 1
}
finally {
    Pop-Location
}
```

- [ ] **Step 3: Verify the file now exists (the "green" state)**

Run:

```bash
test -f scripts/win-tests.ps1 && echo "EXISTS" || echo "ABSENT"
```

Expected: `EXISTS`

- [ ] **Step 4: Commit**

```bash
git add scripts/win-tests.ps1
git commit -m "build: add Windows test tier runner (win-tests.ps1)"
```

---

### Task 7: scripts/run-tests.sh - the dual-tier orchestrator

**Files:**

- Create: `scripts/run-tests.sh`

This is the single command that runs the whole suite. Tier 1 is Podman (Core C# + Python daemon) and must pass on Linux with zero Windows deps. Tier 2 invokes `powershell.exe` for the Windows projects. `FM_SKIP_WIN=1` skips Tier 2 (logged loudly) for Podman-only local iteration. It exits non-zero if either tier it actually runs fails.

> Note on the Python tier: `pytest wsl/tests` is part of Tier 1 per the contract, but the `wsl/` daemon and its tests are created in `02b-daemon`, not here. So `run-tests.sh` runs the pytest step only if `wsl/tests` exists; until `02b-daemon` lands, that step is a logged skip, not a failure. This keeps `run-tests.sh` green at the end of the foundation while still wiring the Python tier for later.

- [ ] **Step 1: Verify the script does not yet exist (the "red" state)**

Run:

```bash
test -x scripts/run-tests.sh && echo "EXECUTABLE" || echo "MISSING"
```

Expected: `MISSING`

- [ ] **Step 2: Create the dual-tier runner**

Create `scripts/run-tests.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

# WinSuperWhisper full test suite. Two tiers:
#   Tier 1 - Podman (Linux): Core C# tests + Python daemon tests. Zero Windows deps.
#   Tier 2 - Windows via powershell.exe from WSL: Win32 adapters + UI smoke.
# Exits non-zero if EITHER tier it runs fails. No human in the loop.
# FM_SKIP_WIN=1 skips Tier 2 (logged loudly) for Podman-only local iteration.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

echo "==================================================="
echo " WinSuperWhisper test suite"
echo " Repo root: ${REPO_ROOT}"
echo "==================================================="

# ---- Tier 1: Podman (Linux) ----------------------------------------------
echo
echo ">> Tier 1 (Podman): Core C# tests"
"${SCRIPT_DIR}/dotnet.sh" test tests/WinSuperWhisper.Tests

echo
echo ">> Tier 1 (Podman): Python daemon tests"
if [ -d "wsl/tests" ]; then
  # Run pytest inside the dotnet SDK container's sibling python, or a python image.
  # The daemon and its tests arrive in 02b-daemon; until then this branch is skipped.
  podman run --rm \
    -v "${REPO_ROOT}:/work:Z" \
    -w /work \
    python:3.12-slim \
    bash -c "pip install --quiet -r wsl/requirements.txt pytest && pytest wsl/tests"
else
  echo "   (skip: wsl/tests not present yet - lands in 02b-daemon)"
fi

echo
echo ">> Tier 1 PASSED"

# ---- Tier 2: Windows via powershell.exe ----------------------------------
echo
if [ "${FM_SKIP_WIN:-0}" = "1" ]; then
  echo "############################################################"
  echo "## FM_SKIP_WIN=1 -> SKIPPING Tier 2 (Windows) tests       ##"
  echo "## Win32 adapters + UI smoke were NOT run.                ##"
  echo "############################################################"
  echo
  echo ">> Suite complete (Tier 1 only; Windows tier skipped)."
  exit 0
fi

echo ">> Tier 2 (Windows via powershell.exe): Win32 adapters + UI smoke"
if ! command -v powershell.exe >/dev/null 2>&1; then
  echo "ERROR: powershell.exe not found on PATH." >&2
  echo "       Run on a WSL host with Windows interop, or set FM_SKIP_WIN=1" >&2
  echo "       to iterate on the Podman tier only." >&2
  exit 1
fi

powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/win-tests.ps1
WIN_STATUS=$?
if [ "${WIN_STATUS}" -ne 0 ]; then
  echo ">> Tier 2 FAILED (exit ${WIN_STATUS})" >&2
  exit "${WIN_STATUS}"
fi

echo
echo ">> Tier 2 PASSED"
echo ">> Suite complete (both tiers green)."
```

Then make it executable:

```bash
chmod +x scripts/run-tests.sh
```

- [ ] **Step 3: Run the suite Podman-only and verify it reaches both tiers cleanly (the "green" state)**

Run:

```bash
FM_SKIP_WIN=1 scripts/run-tests.sh
```

Expected: exit code 0. Output shows Tier 1 running `dotnet test tests/WinSuperWhisper.Tests` green (2 passed - the guardrail tests), the Python step logging `(skip: wsl/tests not present yet ...)`, then the loud `FM_SKIP_WIN=1 -> SKIPPING Tier 2` banner, ending with `Suite complete (Tier 1 only; Windows tier skipped).`

Verify the exit code explicitly:

```bash
FM_SKIP_WIN=1 scripts/run-tests.sh; echo "exit=$?"
```

Expected: final line `exit=0`.

- [ ] **Step 4: Verify the full (non-skip) path reaches the Windows tier boundary**

On this Linux host without Windows interop, the full run must reach Tier 2 and then either invoke `powershell.exe` (on a WSL host) or fail loudly with the actionable message. Confirm it does NOT silently pass:

Run:

```bash
scripts/run-tests.sh; echo "exit=$?"
```

Expected (on a plain Linux host with no `powershell.exe`): Tier 1 green, then `ERROR: powershell.exe not found on PATH.` and `exit=1`. This proves the suite refuses to claim success without the Windows tier unless `FM_SKIP_WIN=1` is set. (On a real WSL host with interop, this instead invokes `win-tests.ps1`; that path is exercised in the Windows-tier phases.)

> This expected `exit=1` is correct behavior, not a failure of the plan: the foundation's binary exit condition for `run-tests.sh` is "exits 0 and reaches both tiers, OR cleanly skips the Win tier with FM_SKIP_WIN=1 and says so". The `FM_SKIP_WIN=1` run in Step 3 is the green gate; Step 4 documents that the non-skip path is honest about the missing Windows tier.

- [ ] **Step 5: Commit**

```bash
git add scripts/run-tests.sh
git commit -m "build: add dual-tier run-tests.sh (Podman + Windows via powershell.exe)"
```

---

## Self-review notes (already reconciled)

- **TFMs:** Core `net8.0`, App `net8.0-windows`, Tests `net8.0`, App.Tests `net8.0-windows` - matches the contract file tree verbatim.
- **References:** Tests->Core (Task 3), App->Core (Task 2), App.Tests->App (Task 4) - all three wired.
- **Paths:** `src/WinSuperWhisper.Core`, `src/WinSuperWhisper.App`, `tests/WinSuperWhisper.Tests`, `tests/WinSuperWhisper.App.Tests`, `scripts/run-tests.sh`, `scripts/win-tests.ps1` - all match the contract file tree.
- **Podman boundary:** only `net8.0` projects (Core, Tests) are built/tested on Linux; `net8.0-windows` projects (App, App.Tests) are created and referenced but built only in the Windows tier - matches the design's "compiles and tests on Linux in Podman" boundary.
- **No placeholders left:** every csproj, the `.gitignore`, `dotnet.sh`, `win-tests.ps1`, and `run-tests.sh` are shown in full; the only intentional placeholder (the Step-1 failing test in Task 5) is explicitly replaced in Step 3 of the same task.

---

## Exit conditions (all must be green)

- [ ] Standalone `WinSuperWhisper` git repo exists with default branch `main`, NOT under firstmate.
- [ ] `WinSuperWhisper.sln` lists exactly four projects with the exact relative paths and TFMs:
  - [ ] `src/WinSuperWhisper.Core` -> `net8.0`
  - [ ] `src/WinSuperWhisper.App` -> `net8.0-windows`
  - [ ] `tests/WinSuperWhisper.Tests` -> `net8.0`
  - [ ] `tests/WinSuperWhisper.App.Tests` -> `net8.0-windows`
- [ ] Project references wired: `Tests -> Core`, `App -> Core`, `App.Tests -> App`.
- [ ] Both test projects carry xUnit + Moq; the repo has a .NET `.gitignore`.
- [ ] `scripts/dotnet.sh build src/WinSuperWhisper.Core` -> `Build succeeded.`, `0 Error(s)` on Linux via Podman.
- [ ] `scripts/dotnet.sh test tests/WinSuperWhisper.Tests --filter "FullyQualifiedName~GuardrailTests"` -> `Passed!  - Failed: 0, Passed: 2` (Core loads on Linux and references no WPF/NAudio).
- [ ] `FM_SKIP_WIN=1 scripts/run-tests.sh` -> exit 0, Tier 1 green, Windows tier cleanly skipped with the loud banner.
- [ ] `scripts/run-tests.sh` (no skip, plain Linux host) -> Tier 1 green, then exits non-zero with the actionable `powershell.exe not found` message (it never claims success without the Windows tier).
- [ ] Each commit is a green tree with the conventional-commit message shown; no red tree was ever committed.

## What unlocks next

Completing this file unlocks **`02a-core`** and **`02b-daemon`**, which run **in parallel** (they share no code):

- `02a-core` (PODMAN) builds on the `WinSuperWhisper.Core` project established here: interfaces, models, `WavEncoder`, `FrameProtocol`, `DaemonClient`, and `DictationOrchestrator` (all mocked), validated by `tests/WinSuperWhisper.Tests` through the same Podman `dotnet.sh` wrapper.
- `02b-daemon` (PODMAN) builds the `wsl/` Python daemon (`whisper_daemon.py`, `requirements.txt`, `install.sh`, `tests/`); once `wsl/tests` exists, the Python step in `run-tests.sh` Tier 1 stops being a skip and runs `pytest wsl/tests` for real.

Both consume the guardrail and the dual-tier `run-tests.sh` unchanged; neither may weaken the Core-has-no-WPF/NAudio assertion.
