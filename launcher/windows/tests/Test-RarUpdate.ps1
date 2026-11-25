param(
    [Parameter(Mandatory)] [string] $Launcher,
    [string] $RarTool = (Join-Path $env:ProgramFiles 'WinRAR\Rar.exe')
)
$ErrorActionPreference = 'Stop'
$Launcher = (Resolve-Path -LiteralPath $Launcher).Path
$RarTool = (Resolve-Path -LiteralPath $RarTool).Path
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$fixture = Join-Path $PSScriptRoot 'UpdateFixture.cs'
$qa = (New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot ('..\..\..\build\launcher-tests\rar-' + [Guid]::NewGuid().ToString('N')))).FullName
$current = [System.Reflection.AssemblyName]::GetAssemblyName($Launcher).Version
$successor = [version]::new($current.Major, $current.Minor, $current.Build + 1, 0)
$payload = (New-Item -ItemType Directory -Path (Join-Path $qa 'payload')).FullName
$install = (New-Item -ItemType Directory -Path (Join-Path $qa 'existing install')).FullName
$target = Join-Path $install 'SM3DL-Launcher.exe'
$next = Join-Path $payload 'SM3DL-Launcher.exe'
$metadataFile = Join-Path $qa 'FixtureVersion.g.cs'
function Build-Fixture([string]$Destination, [version]$Version) {
    [System.IO.File]::WriteAllText($metadataFile, ('[assembly: System.Reflection.AssemblyVersion("{0}")]' -f $Version))
    & $csc /nologo /target:winexe "/out:$Destination" $fixture $metadataFile
    if ($LASTEXITCODE -ne 0) { throw 'Could not build the test launcher executable.' }
}
Build-Fixture $target $current
Build-Fixture $next $successor
$oldHash = (Get-FileHash -LiteralPath $target).Hash
function New-Archive([string]$Destination, [string[]]$Names, [switch]$Encrypted) {
    $passwordSwitch = @()
    if ($Encrypted) { $passwordSwitch = @('-ptest-only-password') }
    Push-Location -LiteralPath $payload
    try {
        & $RarTool a -ma5 -cfg- -ep -idp @passwordSwitch -- $Destination @Names | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the RAR test fixture.' }
    } finally { Pop-Location }
}
$archiveName = 'Super-Mario-3D-Land-Windows-x64-v' + $successor.ToString(3) + '.rar'
$archive = Join-Path $qa $archiveName
New-Archive $archive @('SM3DL-Launcher.exe')
$extra = Join-Path $qa 'archive-with-extra-file.rar'
[System.IO.File]::WriteAllText((Join-Path $payload 'extra.txt'), 'Not part of the launcher.')
New-Archive $extra @('SM3DL-Launcher.exe', 'extra.txt')
$encrypted = Join-Path $qa 'password-protected.rar'
New-Archive $encrypted @('SM3DL-Launcher.exe') -Encrypted
$feed = Join-Path $qa 'feed.json'
$receipt = Join-Path $qa 'receipt.txt'
$repo = 'Okxmir/super-mario-3d-land-recompiled'
function New-Asset([string]$Name, [string]$Path, [string]$Hash) {
    @{
        name = $Name; state = 'uploaded'; digest = "sha256:$Hash"
        size = (Get-Item -LiteralPath $Path).Length
        browser_download_url = "https://github.com/$repo/releases/download/test/$Name"
    }
}
function Get-PreparedExe([string]$RarPath, [string]$Stage, [bool]$Expected) {
    $proc = Start-Process -FilePath $Launcher -ArgumentList ('--verify-rar-update "{0}" "{1}" "{2}" "{3}"' -f $feed,$RarPath,$Stage,$receipt) -WindowStyle Hidden -Wait -PassThru
    $result = Get-Content -LiteralPath $receipt -Raw
    if (($proc.ExitCode -eq 0) -ne $Expected) { throw "Unexpected result: $result" }
    $result
}
function Write-Feed([object[]]$Assets) {
    ConvertTo-Json -InputObject @(@{tag_name='test'; draft=$false; prerelease=$false; assets=$Assets}) -Depth 6 |
        Set-Content -LiteralPath $feed -Encoding utf8
}
$rarAsset = New-Asset $archiveName $archive (Get-FileHash -LiteralPath $archive).Hash
$rawAsset = New-Asset ('SM3DL-Launcher-v' + $successor.ToString(3) + '.exe') $next (Get-FileHash -LiteralPath $next).Hash
Write-Feed @($rawAsset,$rarAsset)
$preferred = Get-PreparedExe $archive (Join-Path $qa 'preferred') $true
if ($preferred -ne (Get-FileHash -LiteralPath $next).Hash) { throw 'The RAR was not preferred or correctly extracted.' }
'RAR wins over a same-version raw EXE.'
Write-Feed @((New-Asset ('SM3DL-Launcher-Windows-x64-v' + $successor.ToString(3) + '.rar') $archive (Get-FileHash -LiteralPath $archive).Hash))
$legacy = Get-PreparedExe $archive (Join-Path $qa 'legacy-name') $true
if ($legacy -ne $preferred) { throw 'The legacy RAR name was not recognized.' }
'Both the new and older RAR asset names are recognized.'

$stage = Join-Path $install ('LauncherData\updates\' + [Guid]::NewGuid().ToString('N'))
Write-Feed @($rarAsset)
$sha = Get-PreparedExe $archive $stage $true
if ($sha -ne (Get-FileHash -LiteralPath $next).Hash) { throw 'The extracted game launcher differs from the RAR source.' }
$helper = Join-Path $stage 'finish-update.exe'
Copy-Item -LiteralPath $Launcher -Destination $helper
$unusedPid = 2147483600
if (Get-Process -Id $unusedPid -ErrorAction SilentlyContinue) { throw 'Unexpected process collision with fixture PID.' }
$proc = Start-Process -FilePath $helper -ArgumentList "--finish-update $unusedPid SM3DL-Launcher.exe $successor $sha" -WindowStyle Hidden -Wait -PassThru
if ($proc.ExitCode -ne 0 -or (Get-Content (Join-Path $install 'restarted-version.txt') -Raw) -ne $successor.ToString() -or
    (Get-FileHash -LiteralPath (Join-Path $stage 'previous.backup')).Hash -ne $oldHash) {
    throw 'The RAR-only update did not restart the new launcher and keep the old copy.'
}
'RAR-only update selected, extracted, verified, installed and restarted.'

Write-Feed @((New-Asset $archiveName $encrypted (Get-FileHash -LiteralPath $encrypted).Hash))
$result = Get-PreparedExe $encrypted (Join-Path $qa 'encrypted') $false
if ($result -notmatch 'could not verify or unpack') { throw "Unexpected response to an encrypted RAR: $result" }
'Password-protected archives were rejected.'

Write-Feed @((New-Asset $archiveName $archive ('0' * 64)))
$result = Get-PreparedExe $archive (Join-Path $qa 'wrong-hash') $false
if ($result -notmatch 'SHA-256' -or (Test-Path -LiteralPath (Join-Path $qa 'wrong-hash\rar-reader.exe'))) {
    throw "Wrong archive was not blocked before unpacking: $result"
}
Write-Feed @((New-Asset $archiveName $extra (Get-FileHash -LiteralPath $extra).Hash))
$result = Get-PreparedExe $extra (Join-Path $qa 'extra-file') $false
if ($result -notmatch 'only SM3DL-Launcher.exe') { throw "Unexpected response to extra archive entry: $result" }
$wrongName = 'Super-Mario-3D-Land-Windows-x64-v' + ([version]::new($successor.Major, $successor.Minor, $successor.Build + 1)).ToString(3) + '.rar'
Write-Feed @((New-Asset $wrongName $archive (Get-FileHash -LiteralPath $archive).Hash))
$result = Get-PreparedExe $archive (Join-Path $qa 'wrong-version') $false
if ($result -notmatch 'advertised version') { throw "Unexpected response to wrong executable version: $result" }
'Wrong checksums, extra archive entries and mismatched executable versions were rejected.'

$sameName = 'Super-Mario-3D-Land-Windows-x64-v' + $current.ToString(3) + '.rar'
Write-Feed @((New-Asset $sameName $archive (Get-FileHash -LiteralPath $archive).Hash))
$result = Get-PreparedExe $archive (Join-Path $qa 'same-version') $false
if ($result -notmatch 'cannot downgrade') { throw "Unexpected response to an equal launcher version: $result" }
'An equal launcher version cannot replace the running build.'
