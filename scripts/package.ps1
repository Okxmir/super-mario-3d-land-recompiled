param(
    [ValidateSet('Release','Debug')] [string] $Configuration = 'Release',
    [ValidateSet('en','fr','de','it','es','nl','pt','ru')] [string] $Language,
    [string] $OutputDirectory,
    [switch] $Portable
)
. "$PSScriptRoot/common.ps1"
$dist = if ($OutputDirectory) {
    $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDirectory)
} else {
    Join-Path $ProjectRoot 'dist'
}
$licenses = Join-Path $dist 'licenses'
$build = Get-Sm3dlBuildDirectory $Configuration ([bool]$Portable)
Push-Location -LiteralPath $ProjectRoot
try {
    New-Item -ItemType Directory -Path $dist,$licenses -Force | Out-Null
    Copy-Item -LiteralPath "$build/SuperMario3DLandRecompiled.exe",
        "$build/SDL3.dll", 'extracted/SM3DL-EUR.cxi',
        'extracted/mii.romfs', 'extracted/shared-font.bcfnt' -Destination $dist -Force
    Copy-Item -LiteralPath 'licenses/Clockwork.txt', 'licenses/CityHash.txt' -Destination $licenses -Force
    Copy-Item -LiteralPath 'build/upstream/SDL3-3.4.0/LICENSE.txt' -Destination "$licenses/SDL.txt" -Force

    Copy-Item -LiteralPath 'licenses/LuigisMansion2Recompiled.txt' -Destination $licenses -Force
    Copy-Item -LiteralPath 'build/upstream/xbyak-df112862583c2d327c1d9782fd28f53aa675f11d/COPYRIGHT' -Destination "$licenses/Xbyak.txt" -Force
    $systemLicense = 'build/upstream/citra_system_archives-f470e0c9d341db73b8a24880295d2eab4cd81660/license.txt'
    Copy-Item -LiteralPath $systemLicense -Destination "$licenses/SystemArchives.txt" -Force
    if ($Portable) {
        $llvm = Join-Path $ProjectRoot 'build/p/llvm'
        Copy-Item -LiteralPath "$llvm/LICENSE.TXT" -Destination "$licenses/LLVM.txt" -Force
        $mingwNotices = "$llvm/x86_64-w64-mingw32/share/mingw32"
        Copy-Item -LiteralPath "$mingwNotices/COPYING.MinGW-w64-runtime.txt", "$mingwNotices/COPYING.winpthreads.txt" -Destination $licenses -Force
    }
    if ($Language) {
        $languageIds = @{ en = 1; fr = 2; de = 3; it = 4; es = 5; nl = 8; pt = 9; ru = 10 }
        $settings = Join-Path $dist 'userdata/settings.ini'
        New-Item -ItemType Directory -Path (Split-Path -Parent $settings) -Force | Out-Null
        $lines = @()
        if (Test-Path -LiteralPath $settings) {
            $lines = [IO.File]::ReadAllLines($settings) -notmatch '^language='
        }
        [IO.File]::WriteAllLines($settings, [string[]]($lines + "language=$($languageIds[$Language])"))
        Write-Host "Game language: $($Language.ToLowerInvariant())"
    }
    Write-Host "Windows build: $(Join-Path $dist 'SuperMario3DLandRecompiled.exe')"
} finally {
    Pop-Location
}
