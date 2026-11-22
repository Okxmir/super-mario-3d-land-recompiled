param(
    [string] $Cartridge,
    [string] $KeyFile,
    [switch] $Portable
)
. "$PSScriptRoot/common.ps1"

if ($Cartridge) { $Cartridge = (Resolve-Path -LiteralPath $Cartridge).Path }
if ($KeyFile) { $KeyFile = (Resolve-Path -LiteralPath $KeyFile).Path }
$resourceProcess = $null
$resourceScript = Join-Path $PSScriptRoot 'prepare_system.ps1'
Push-Location -LiteralPath $ProjectRoot
try {
    $ProgressPreference = 'SilentlyContinue'
    $upstream = Join-Path $ProjectRoot 'build/upstream'
    New-Item -ItemType Directory -Path $upstream, 'logs' -Force | Out-Null

    # Fonts and Mii resources do not depend on the ROM or the native recompiler.
    if (!$Portable -and (Get-Sm3dlBuildJobs) -gt 1) {
        $resourceStart = New-Object System.Diagnostics.ProcessStartInfo
        $resourceStart.FileName = Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
        $resourceStart.Arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f $resourceScript
        $resourceStart.WorkingDirectory = $ProjectRoot
        $resourceStart.UseShellExecute = $false
        $resourceStart.CreateNoWindow = $true
        $resourceStart.RedirectStandardOutput = $true
        $resourceStart.RedirectStandardError = $true
        try {
            $resourceProcess = [System.Diagnostics.Process]::Start($resourceStart)
        } catch {
            Write-Host 'The resource worker could not start. Preparing resources after ARM recompilation.'
        }
        if ($resourceProcess) {
            $resourceOutput = $resourceProcess.StandardOutput.ReadToEndAsync()
            $resourceErrors = $resourceProcess.StandardError.ReadToEndAsync()
            Write-Host 'Preparing game resources in parallel with the build tools and ARM recompilation.'
        }
    }

    function Get-VerifiedArchive([string] $Name, [string] $Url, [string] $Sha256) {
        $path = Join-Path $upstream $Name
        if (!(Test-Path -LiteralPath $path)) {
            $partial = "$path.partial"
            Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $partial -TimeoutSec 240
            if ((Get-Sha256 $partial) -ne $Sha256) {
                throw "SHA-256 mismatch for $Name"
            }
            Move-Item -LiteralPath $partial -Destination $path
        }
        if ((Get-Sha256 $path) -ne $Sha256) {
            throw "SHA-256 mismatch for $Name"
        }
        $path
    }

    $commit = '3047d9e990be4ac2c84174cb570dfec569c882e9'
    $clockwork = Get-VerifiedArchive 'clockwork-pinned.zip' `
        "https://codeload.github.com/watchmakerers/clockwork/zip/$commit" `
        '7923E82994E3A06F7AA17DFDB2A6E25A608E3495227BAF1A0FDBCC32DFBE1DED'
    $sdl = Get-VerifiedArchive 'SDL3-devel-3.4.0-VC.zip' `
        'https://github.com/libsdl-org/SDL/releases/download/release-3.4.0/SDL3-devel-3.4.0-VC.zip' `
        '4489BA0070B8CE047B8717E4B71FA7E35AC71362E7A6BB2A90A7A27F624B3D5D'
    $memmap = Get-VerifiedArchive 'memmap2-0.9.11.crate' `
        'https://static.crates.io/crates/memmap2/memmap2-0.9.11.crate' `
        'D1219ED1B7F229EE7104D281DD01D6802FE28BB6E95D292942C4DAACDEB798C0'
    $alonPatch = Get-VerifiedArchive 'alon-60fps-0.2-preview.ips' `
        'https://raw.githubusercontent.com/AlonBorodAHub/mario-3d-land-60fps/eab11f6cc03c9df6ba06cd56af1ac28e7cf64a09/patch/code.ips' `
        '6CDC315748EB2EB1461ED5447BB9FDB65B195D49F4237BD760BBF5166BD2004F'

    if (!(Test-Path -LiteralPath "$upstream/clockwork-master/tools/recomp/src/main.rs")) {
        Expand-Archive -LiteralPath $clockwork -DestinationPath $upstream -Force
        New-Item -ItemType Directory -Force -Path "$upstream/clockwork-master" | Out-Null
        Copy-Item -Path "$upstream/clockwork-$commit/*" -Destination "$upstream/clockwork-master" -Recurse -Force
    }
    if (!(Test-Path -LiteralPath "$upstream/SDL3-3.4.0/cmake/SDL3Config.cmake")) {
        Expand-Archive -LiteralPath $sdl -DestinationPath $upstream -Force
    }
    $dxc = Get-VerifiedArchive 'dxc_2025_07_14.zip' 'https://github.com/microsoft/DirectXShaderCompiler/releases/download/v1.8.2505.1/dxc_2025_07_14.zip' '9AD895A6B039E3A8F8C22A1009F866800B840A74B50DB9218D13319E215EA8A4'
    $dxcDir = Join-Path $upstream 'dxc-1.8.2505.1'
    if (!(Test-Path -LiteralPath "$dxcDir/bin/x64/dxc.exe")) {
        Expand-Archive -LiteralPath $dxc -DestinationPath $dxcDir -Force
    }
    $xbyakCommit = 'df112862583c2d327c1d9782fd28f53aa675f11d'
    $xbyak = Get-VerifiedArchive 'xbyak-pinned.zip' "https://codeload.github.com/herumi/xbyak/zip/$xbyakCommit" 'B0E8D74A5813D4C4D2BAA550B889B7F7C2696E471DFB8DE1554CE47F7E52D7F8'
    if (!(Test-Path -LiteralPath "$upstream/xbyak-$xbyakCommit/xbyak/xbyak.h")) {
        Expand-Archive -LiteralPath $xbyak -DestinationPath $upstream -Force
    }
    tar.exe -xf $memmap -C $upstream
    if ($LASTEXITCODE -ne 0) { throw "Could not unpack $memmap" }
    if ($Portable) {
        & scripts/build_tools.cmd "$ProjectRoot/build/p/rust/bin/rustc.exe" portable
    } else {
        $rustVersion = '1.90.0-x86_64-pc-windows-msvc'
        $rustc = Get-VerifiedArchive "rustc-$rustVersion.tar.xz" `
            "https://static.rust-lang.org/dist/rustc-$rustVersion.tar.xz" `
            'A18B3912905F154C34A7572954DDA9E9849AC6411A1E02FA390BF742F918FBCB'
        $rustStd = Get-VerifiedArchive "rust-std-$rustVersion.tar.xz" `
            "https://static.rust-lang.org/dist/rust-std-$rustVersion.tar.xz" `
            '3B8C22F81C93C7E914369433430792BD6C06403806AE25B0B95F3CFC540A8B48'
        foreach ($archive in @($rustc, $rustStd)) {
            tar.exe -xf $archive -C $upstream
            if ($LASTEXITCODE -ne 0) { throw "Could not unpack $archive" }
        }
        $compiler = Join-Path $upstream "rustc-$rustVersion/rustc"
        $standardLib = Join-Path $upstream "rust-std-$rustVersion/rust-std-x86_64-pc-windows-msvc/lib/rustlib/x86_64-pc-windows-msvc/lib"
        $targetLib = Join-Path $compiler 'lib/rustlib/x86_64-pc-windows-msvc/lib'
        New-Item -ItemType Directory -Path $targetLib -Force | Out-Null
        Copy-Item -Path "$standardLib/*" -Destination $targetLib -Recurse -Force
        $vs = Find-Sm3dlVisualStudio
        & scripts/build_tools.cmd (Join-Path $vs 'Common7/Tools/VsDevCmd.bat')
    }
    if ($LASTEXITCODE -ne 0) { throw 'Could not build the extraction and recompilation tools.' }

    Write-Host 'Build stage: Extracting the ROM'
    $cxi = 'extracted/SM3DL-EUR.cxi'
    if (!(Test-Path -LiteralPath $cxi) -or $Cartridge) {
        $staging = 'extracted/SM3DL-EUR.pending.cxi'
        if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging }
        $options = @('--extract', $staging)
        if ($Cartridge) { $options += $Cartridge }
        if ($KeyFile) { $options += @('--key-file', $KeyFile) }
        python tools/cartridge.py @options
        if ($LASTEXITCODE -ne 0) { throw 'Could not extract the game partition.' }
        $inputImage = $staging
    } else {
        $inputImage = $cxi
    }
    python tools/verify_extraction.py $inputImage
    if ($LASTEXITCODE -ne 0) { throw 'The extracted game partition did not pass its integrity check.' }
    & build/tools/ctrx.exe --code-only $inputImage extracted/sm3dl-eur | Tee-Object -FilePath logs/extraction.txt
    if ($LASTEXITCODE -ne 0) { throw 'Could not unpack the game executable.' }
    $expected = 'E1D7E188FF88467DF776C17CEC45C44857FADF5B699944BAA8CDDCAE7D939E64'
    if ((Get-Sha256 'extracted/sm3dl-eur/code.bin') -ne $expected) {
        throw 'The game code does not match the supported European revision.'
    }
    if ($inputImage -ne $cxi) { Move-Item -LiteralPath $inputImage -Destination $cxi -Force }

    Write-Host 'Build stage: Recompiling ARM code'
    $generated = 'generated/sm3dl-eur'
    $stagedCode = 'build/generated-staging'
    New-Item -ItemType Directory -Path $generated,$stagedCode -Force | Out-Null
    Get-ChildItem -LiteralPath $stagedCode -File | Remove-Item
    $patchedCode = 'build/alon-eur-code'
    python tools/relocate_alon.py $alonPatch extracted/sm3dl-eur $patchedCode "$stagedCode/alon_eur_payload.inc"
    if ($LASTEXITCODE -ne 0) { throw 'Could not adapt the native 60 FPS patch for the verified European code.' }
    & build/tools/recomp.exe emit $patchedCode $stagedCode | Tee-Object -FilePath logs/recompile.txt
    if ($LASTEXITCODE -ne 0) { throw 'Native code generation failed.' }
    $nextFiles = Get-ChildItem -LiteralPath $stagedCode -File
    foreach ($file in $nextFiles) {
        $destination = Join-Path $generated $file.Name
        if (!(Test-Path -LiteralPath $destination) -or (Get-Sha256 $destination) -ne (Get-Sha256 $file.FullName)) {
            Copy-Item -LiteralPath $file.FullName -Destination $destination -Force
        }
    }
    Get-ChildItem -LiteralPath $generated -File | Where-Object { $_.Name -notin $nextFiles.Name } | Remove-Item
    Write-Host 'Build stage: Preparing game resources'
    if ($resourceProcess) {
        $resourceProcess.WaitForExit()
        foreach ($stream in $resourceOutput,$resourceErrors) {
            $message = $stream.GetAwaiter().GetResult().TrimEnd()
            if ($message) { Write-Host $message }
        }
        if ($resourceProcess.ExitCode -ne 0) { throw "Game resource generation failed ($($resourceProcess.ExitCode))." }
    } else {
        & $resourceScript -Portable:$Portable
    }
} finally {
    if ($resourceProcess) {
        $resourceProcess.WaitForExit()
        $resourceProcess.Dispose()
    }
    Pop-Location
}
