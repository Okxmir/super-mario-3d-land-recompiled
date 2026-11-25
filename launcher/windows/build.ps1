param(
    [string] $GameProject = (Join-Path $PSScriptRoot '..\..'),
    [string] $OutputDirectory = (Join-Path $PSScriptRoot '..\..\dist\launcher-windows'),
    [switch] $ReleaseAsset,
    [switch] $IncludeLegacyExe,
    [string] $RarTool
)
$ErrorActionPreference = 'Stop'

function Invoke-ReleaseRar([string]$Tool, [string]$WorkingDirectory, [string]$Arguments) {
    $start = New-Object System.Diagnostics.ProcessStartInfo -ArgumentList $Tool, $Arguments
    $start.WorkingDirectory = $WorkingDirectory
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.EnvironmentVariables.Remove('RAR')
    $start.EnvironmentVariables.Remove('RARINISWITCHES')
    $proc = [System.Diagnostics.Process]::Start($start)
    try {
        $proc.StandardInput.Close()
        if (!$proc.WaitForExit(30000)) {
            $proc.Kill()
            throw 'RAR packaging or password-free extraction timed out.'
        }
        if ($proc.ExitCode -ne 0) { throw "RAR packaging or password-free extraction failed (exit $($proc.ExitCode))." }
    } finally { $proc.Dispose() }
}

$core = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'LauncherCore.cs') -Raw
$pinnedRevision = [regex]::Match($core, 'const string Revision = "([0-9a-f]{7,40})";')
if (!$pinnedRevision.Success) { throw 'LauncherCore.cs does not declare a pinned game source revision.' }
$revision = $pinnedRevision.Groups[1].Value
$framework = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319'
$wpf = Join-Path $framework 'WPF'
$csc = Join-Path $framework 'csc.exe'
$null = New-Item -ItemType Directory -Path $OutputDirectory -Force
$output = Join-Path $OutputDirectory 'SM3DL-Launcher.exe'
$archive = Join-Path $OutputDirectory 'GameSources.zip'
$markup = Join-Path $PSScriptRoot 'LauncherStudio.xaml'
$controlMarkup = Join-Path $PSScriptRoot 'ControlsWorkbench.xaml'
$sdl = Join-Path $PSScriptRoot 'assets\SDL3.dll'
$sdlLicense = Join-Path $PSScriptRoot 'assets\SDL3-LICENSE.txt'
$unrar = Join-Path $PSScriptRoot 'assets\UnRAR.exe'
$unrarNotice = Join-Path $PSScriptRoot 'assets\UnRAR-NOTICE.txt'
if ((Get-FileHash -LiteralPath $sdl).Hash -ne '2632E21625861A0DC106F2B1ABB649E610D8BE88534BA74C76A763ABE5AEFAA3') {
    throw 'The embedded SDL3 controller library does not match the expected build.'
}
if ((Get-FileHash -LiteralPath $unrar).Hash -ne '0D3715001790F0FD18D3E850F947B540530B2D2DEB9A2E6A9E84F2ED7B234235') {
    throw 'The embedded RAR reader does not match the expected build.'
}
$png = Join-Path $PSScriptRoot '..\icon.png'
$icon = Join-Path $OutputDirectory 'LauncherIcon.ico'
& (Join-Path $PSScriptRoot 'New-LauncherIcon.ps1') -Source $png -Destination $icon
& git -C $GameProject archive --format=zip "--output=$archive" $revision -- CMakeLists.txt BUILD.md LICENSE build.cmd build.sh licenses scripts src tools
if ($LASTEXITCODE -ne 0) { throw "Could not archive game sources at $revision." }
$files = 'Program.cs', 'StudioLauncher.cs', 'LauncherActions.cs', 'LauncherCore.cs', 'LauncherUpdater.cs', 'UpdateUi.cs',
    'ControlBindings.cs', 'ControlsEditor.cs', 'SdlInput.cs', 'RarUpdate.cs' | ForEach-Object { Join-Path $PSScriptRoot $_ }
$references = 'PresentationFramework.dll', 'PresentationCore.dll', 'WindowsBase.dll' | ForEach-Object { "/reference:$wpf\$_" }
$references += 'System.Xaml.dll', 'System.IO.Compression.dll', 'System.Web.Extensions.dll' | ForEach-Object { "/reference:$framework\$_" }
& $csc /nologo /target:winexe /platform:x64 /optimize+ /codepage:65001 "/out:$output" "/win32icon:$icon" "/resource:$archive,GameSources.zip" "/resource:$markup,Launcher.xaml" "/resource:$png,LauncherIcon.png" "/resource:$controlMarkup,ControlsWorkbench.xaml" "/resource:$sdl,Controls.SDL3.dll" "/resource:$sdlLicense,SDL3-LICENSE.txt" "/resource:$unrar,Update.UnRAR.exe" "/resource:$unrarNotice,UnRAR-NOTICE.txt" @references @files
if ($LASTEXITCODE -ne 0) { throw 'Launcher compilation failed.' }
Write-Host $output
if ($ReleaseAsset) {
    $version = [System.Reflection.AssemblyName]::GetAssemblyName($output).Version.ToString(3)
    $dist = Join-Path $OutputDirectory 'release'
    $dist = (New-Item -ItemType Directory -Path $dist -Force).FullName
    if (!$RarTool) {
        $onPath = Get-Command rar.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        $RarTool = if ($onPath) { $onPath.Source } else { Join-Path $env:ProgramFiles 'WinRAR\Rar.exe' }
    }
    if (!(Test-Path -LiteralPath $RarTool -PathType Leaf)) {
        throw 'RAR packaging requires Rar.exe on the publisher PC. Pass -RarTool to select it.'
    }
    $RarTool = (Resolve-Path -LiteralPath $RarTool).Path
    $asset = Join-Path $dist "Super-Mario-3D-Land-Windows-x64-v$version.rar"
    if (Test-Path -LiteralPath $asset) { throw "The RAR asset already exists. Use a fresh output directory or bump the version." }
    $stage = (New-Item -ItemType Directory -Path (Join-Path $dist ('.rar-check-' + [Guid]::NewGuid().ToString('N')))).FullName
    $candidate = Join-Path $stage 'launcher.rar'
    $extracted = Join-Path $stage 'SM3DL-Launcher.exe'
    try {
        # Do not supply any password switch when creating or extracting the release.
        Invoke-ReleaseRar $RarTool (Resolve-Path -LiteralPath $OutputDirectory).Path ('a -ma5 -cfg- -ep -idp -- "{0}" SM3DL-Launcher.exe' -f $candidate)
        Invoke-ReleaseRar $RarTool $stage ('x -cfg- -idp -- "{0}"' -f $candidate)
        if ((Get-FileHash -LiteralPath $extracted).Hash -ne (Get-FileHash -LiteralPath $output).Hash) {
            throw 'The launcher extracted without a password does not match the compiled launcher.'
        }
        [System.IO.File]::Move($candidate, $asset)
    } finally {
        [System.IO.File]::Delete($extracted)
        [System.IO.File]::Delete($candidate)
        [System.IO.Directory]::Delete($stage)
    }
    Get-FileHash -LiteralPath $asset -Algorithm SHA256
    if ($IncludeLegacyExe) {
        $legacy = Join-Path $dist "SM3DL-Launcher-v$version.exe"
        Copy-Item -LiteralPath $output -Destination $legacy
        Get-FileHash -LiteralPath $legacy -Algorithm SHA256
    }
}
