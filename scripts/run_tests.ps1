param(
    [ValidateSet('Release', 'Debug')] [string] $Configuration = 'Release',
    [switch] $Portable
)
. "$PSScriptRoot/common.ps1"
$ctest = if ($Portable) { "$ProjectRoot/build/p/cmake/bin/ctest.exe" } else {
    Join-Path (Find-Sm3dlVisualStudio) 'Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/ctest.exe'
}
& $ctest --test-dir (Get-Sm3dlBuildDirectory $Configuration ([bool]$Portable)) --output-on-failure --no-tests=error -V
if ($LASTEXITCODE -ne 0) { throw "Tests failed ($LASTEXITCODE)." }
