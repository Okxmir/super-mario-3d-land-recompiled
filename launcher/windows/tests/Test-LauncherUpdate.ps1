param(
    [Parameter(Mandatory)] [string] $Launcher,
    [Parameter(Mandatory)] [string] $LinkedGame,
    [Parameter(Mandatory)] [string] $Rom
)
$ErrorActionPreference = 'Stop'
$Launcher = (Resolve-Path -LiteralPath $Launcher).Path
$qa = Join-Path $PSScriptRoot ('..\..\..\build\launcher-tests\update-' + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $qa
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$fixture = Join-Path $PSScriptRoot 'UpdateFixture.cs'
$current = [System.Reflection.AssemblyName]::GetAssemblyName($Launcher).Version
$newVersion = [version]::new($current.Major, $current.Minor, $current.Build + 1, 0)
$otherVersion = [version]::new($current.Major + 1, 0, 0, 0).ToString(3)
$fixtureMetadata = Join-Path (Resolve-Path -LiteralPath $qa).Path 'FixtureVersion.g.cs'

function Build-Fixture([string]$Exe,[version]$Version) {
    [System.IO.File]::WriteAllText($fixtureMetadata, ('[assembly: System.Reflection.AssemblyVersion("{0}")]' -f $Version))
    & $csc /nologo /target:winexe "/out:$Exe" $fixture $fixtureMetadata
    if ($LASTEXITCODE -ne 0) { throw "Could not build the $Version fixture." }
}

function Invoke-Launcher([string]$Exe, [string]$Arguments) {
    $process = Start-Process -FilePath $Exe -ArgumentList $Arguments -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Launcher test failed with exit code $($process.ExitCode): $Arguments" }
}

foreach ($mode in 'wizard','launch','rebuild') {
    $receipt = Join-Path $qa "$mode.txt"
    $source = if ($mode -eq 'wizard') { $Rom } else { $LinkedGame }
    Invoke-Launcher $Launcher ('--verify-{0} "{1}" "{2}" "{3}"' -f $mode, (Join-Path $qa $mode), $source, $receipt)
    Get-Content -LiteralPath $receipt
}

$repo = 'Okxmir/super-mario-3d-land-recompiled'
function New-ReleaseAsset([string]$Tag,[string]$Version, [string]$Digest = ('a' * 64), [string]$HostName = 'github.com') {
    $name = "SM3DL-Launcher-v$Version.exe"
    @{
        name = $name
        state = 'uploaded'
        digest = "sha256:$Digest"
        size = 19000
        browser_download_url = "https://$HostName/$repo/releases/download/$Tag/$name"
    }
}
$fake = @(
    @{ tag_name='v-test'; draft=$false; prerelease=$false; assets=@((New-ReleaseAsset 'v-test' $newVersion.ToString(3)), (New-ReleaseAsset 'v-test' $otherVersion -HostName 'example.com'), (New-ReleaseAsset 'v-test' $otherVersion -Digest 'bad')) }
    @{ tag_name='beta'; draft=$false; prerelease=$true; assets=@((New-ReleaseAsset 'beta' $otherVersion)) }
    @{ tag_name='draft'; draft=$true; prerelease=$false; assets=@((New-ReleaseAsset 'draft' $otherVersion)) }
)
$feed = Join-Path $qa 'release-fixture.json'
ConvertTo-Json -InputObject $fake -Depth 7 | Set-Content -LiteralPath $feed -Encoding utf8
$parsed = Join-Path $qa 'release-selection.txt'
Invoke-Launcher $Launcher ('--verify-release-feed "{0}" "{1}"' -f $feed,$parsed)
if ((Get-Content -LiteralPath $parsed -Raw) -ne $newVersion.ToString()) { throw 'GitHub feed parser selected an unsafe asset.' }
'GitHub release selection rejected drafts, prereleases, wrong hosts and invalid digests.'

foreach ($scenario in 'valid','tampered') {
    $install = Join-Path $qa $scenario
    $data = Join-Path $install 'LauncherData'
    $stage = Join-Path $data ('updates\' + [Guid]::NewGuid().ToString('N'))
    $payloadBuild = Join-Path $install 'payload'
    New-Item -ItemType Directory -Path $stage,$payloadBuild | Out-Null
    $target = Join-Path $install 'SM3DL-Launcher.exe'
    $next = Join-Path $payloadBuild 'SM3DL-Launcher.exe'
    Build-Fixture $target $current
    Build-Fixture $next $newVersion
    $previousHash = (Get-FileHash -LiteralPath $target).Hash
    $helper = Join-Path $stage 'finish-update.exe'
    Copy-Item -LiteralPath $Launcher -Destination $helper
    Copy-Item -LiteralPath $next -Destination (Join-Path $stage 'download.exe')
    $digest = if ($scenario -eq 'valid') { (Get-FileHash -LiteralPath $next).Hash } else { '0' * 64 }
    $unusedPid = 2147483600
    if (Get-Process -Id $unusedPid -ErrorAction SilentlyContinue) { throw 'Unexpected process collision with fixture PID.' }
    Invoke-Launcher $helper "--finish-update $unusedPid SM3DL-Launcher.exe $newVersion $digest"
    $note = Join-Path $install 'restarted-version.txt'
    $v = Get-Content -LiteralPath $note -Raw
    if ($scenario -eq 'valid') {
        if ($v -ne $newVersion.ToString() -or (Get-FileHash -LiteralPath (Join-Path $stage 'previous.backup')).Hash -ne $previousHash) {
            throw 'The valid update did not replace, restart and back up the installed executable.'
        }
        'Windows update replaced the verified file, restarted the new application, and kept the old copy.'
    } else {
        if ($v -ne $current.ToString() -or (Get-FileHash -LiteralPath $target).Hash -ne $previousHash) {
            throw 'A corrupt download replaced the installed launcher.'
        }
        'Windows update refused the wrong digest and reopened the intact previous application.'
    }
}
