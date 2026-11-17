param(
    [string] $Cartridge,
    [string] $KeyFile,
    [ValidateSet('Release','Debug')] [string] $Configuration = 'Release',
    [ValidateSet('en','fr','de','it','es','nl','pt','ru')] [string] $Language,
    [string] $OutputDirectory,
    [switch] $Portable
)
. "$PSScriptRoot/common.ps1"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
Write-Host 'Build stage: Preparing dependencies'
if ($Portable) {
    . "$PSScriptRoot/portable_tools.ps1"
    Initialize-Sm3dlPortableTools
}
& "$PSScriptRoot/prepare.ps1" -Cartridge $Cartridge -KeyFile $KeyFile -Portable:$Portable
Write-Host 'Build stage: Compiling the game'
$fast = if ($Configuration -eq 'Debug') { 'ON' } else { 'OFF' }
if ($Portable) { Build-Sm3dlPortable $Configuration $fast }
else { Build-Sm3dl $Configuration $fast }
Write-Host 'Build stage: Running tests'
& "$PSScriptRoot/run_tests.ps1" -Configuration $Configuration -Portable:$Portable
Write-Host 'Build stage: Writing game files'
$packageOptions = @{ Configuration = $Configuration; Portable = $Portable }
if ($Language) { $packageOptions.Language = $Language }
if ($OutputDirectory) { $packageOptions.OutputDirectory = $OutputDirectory }
& "$PSScriptRoot/package.ps1" @packageOptions
