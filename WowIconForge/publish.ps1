<#
.SYNOPSIS
    Publishes WoW Icon Forge as a self-contained win-x64 build, and optionally
    builds the Inno Setup installer.

.DESCRIPTION
    Self-contained means the user needs no .NET runtime installed - the whole
    thing is xcopy-deployable. win-x64 because DirectML is Windows-only.

    The output is a folder of loose files, deliberately not a single file:
    ONNX Runtime and DirectML load native libraries by name, and single-file
    publishing forces an extract-to-temp step that is slower and breaks GPU
    enumeration on some drivers.

.PARAMETER Configuration
    Release (default) or Debug.

.PARAMETER OutputDirectory
    Where to publish. Defaults to .\dist\app.

.PARAMETER ModelsDirectory
    Optional folder of ONNX model files to bundle. When given, its contents are
    copied to <output>\models and the app will find them with no download and
    no first-run wizard. Leaving it off produces a small installer whose first
    run downloads the models instead.

.PARAMETER Installer
    Also compile installer\WowIconForge.iss with Inno Setup 6.

.EXAMPLE
    .\publish.ps1
    Publish only, no bundled models. Installer will be a few hundred MB.

.EXAMPLE
    .\publish.ps1 -ModelsDirectory C:\sd15-onnx -Installer
    Publish with models baked in and build the installer. Expect several GB.
#>
[CmdletBinding()]
param(
    [ValidateSet('Release', 'Debug')]
    [string] $Configuration = 'Release',

    [string] $OutputDirectory = (Join-Path $PSScriptRoot 'dist\app'),

    [string] $ModelsDirectory,

    [switch] $Installer
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$appProject = Join-Path $PSScriptRoot 'src\WowIconForge.App\WowIconForge.App.csproj'
$testProject = Join-Path $PSScriptRoot 'tests\WowIconForge.Core.Tests\WowIconForge.Core.Tests.csproj'
$issScript = Join-Path $PSScriptRoot 'installer\WowIconForge.iss'

function Write-Step($message) {
    Write-Host ''
    Write-Host "==> $message" -ForegroundColor Cyan
}

if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    throw 'dotnet was not found on PATH. Install the .NET 8 SDK.'
}

Write-Step 'Running tests'
dotnet test $testProject --configuration $Configuration --nologo
if ($LASTEXITCODE -ne 0) { throw "Tests failed with exit code $LASTEXITCODE." }

Write-Step "Publishing self-contained win-x64 to $OutputDirectory"
if (Test-Path $OutputDirectory) {
    # A stale publish folder silently keeps files that are no longer produced,
    # which then ship in the installer.
    Remove-Item -Recurse -Force $OutputDirectory
}

dotnet publish $appProject `
    --configuration $Configuration `
    --runtime win-x64 `
    --self-contained true `
    --output $OutputDirectory `
    -p:PublishSingleFile=false `
    -p:PublishReadyToRun=true `
    --nologo
if ($LASTEXITCODE -ne 0) { throw "Publish failed with exit code $LASTEXITCODE." }

$exePath = Join-Path $OutputDirectory 'WowIconForge.exe'
if (-not (Test-Path $exePath)) {
    throw "Publish finished but $exePath is missing."
}

if ($ModelsDirectory) {
    Write-Step "Bundling models from $ModelsDirectory"

    if (-not (Test-Path $ModelsDirectory)) {
        throw "ModelsDirectory '$ModelsDirectory' does not exist."
    }

    # Fail early rather than shipping an installer whose models are incomplete.
    $required = @(
        'unet\model.onnx',
        'vae_decoder\model.onnx',
        'text_encoder\model.onnx',
        'tokenizer\vocab.json',
        'tokenizer\merges.txt'
    )
    $missing = $required | Where-Object { -not (Test-Path (Join-Path $ModelsDirectory $_)) }
    if ($missing) {
        throw "These required model files are missing from '$ModelsDirectory':`n  " + ($missing -join "`n  ")
    }

    $modelTarget = Join-Path $OutputDirectory 'models'
    Copy-Item -Recurse -Force -Path $ModelsDirectory -Destination $modelTarget
    Write-Host "    bundled $([math]::Round((Get-ChildItem $modelTarget -Recurse -File | Measure-Object Length -Sum).Sum / 1GB, 2)) GB"
}

$sizeBytes = (Get-ChildItem $OutputDirectory -Recurse -File | Measure-Object Length -Sum).Sum
Write-Host ''
Write-Host "Published to $OutputDirectory ($([math]::Round($sizeBytes / 1MB, 1)) MB)" -ForegroundColor Green

if ($Installer) {
    Write-Step 'Building installer'

    $iscc = Get-Command 'iscc.exe' -ErrorAction SilentlyContinue
    if (-not $iscc) {
        $candidates = @(
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
        )
        $found = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
        if (-not $found) {
            throw "Inno Setup 6 was not found. Install it from https://jrsoftware.org/isdl.php, or add ISCC.exe to PATH."
        }
        $iscc = $found
    }
    else {
        $iscc = $iscc.Source
    }

    & $iscc "/DAppSourceDir=$OutputDirectory" $issScript
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed with exit code $LASTEXITCODE." }

    Write-Host ''
    Write-Host "Installer written to $(Join-Path $PSScriptRoot 'dist')" -ForegroundColor Green
}
