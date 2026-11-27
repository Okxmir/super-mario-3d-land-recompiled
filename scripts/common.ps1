$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot

function Get-Sm3dlSystemTar {
    # Never resolve tar through PATH: DevkitPro, MSYS2, Git and Cygwin can
    # supply GNU tar, which interprets C:\... as a remote host. Sysnative
    # also covers a 32-bit PowerShell process on 64-bit Windows.
    @('Sysnative/tar.exe', 'System32/tar.exe') | ForEach-Object {
        Join-Path $env:SystemRoot $_
    } | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
}

function Expand-Sm3dlArchive([string] $Archive, [string] $Destination, [ValidateRange(0, 100)][int] $Strip = 0) {
    $archivePath = (Resolve-Path -LiteralPath $Archive).Path
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    $destinationPath = (Resolve-Path -LiteralPath $Destination).Path
    $systemTar = Get-Sm3dlSystemTar
    if ($systemTar) {
        # Ignore archived timestamps, which may be unsupported on FAT/exFAT.
        $arguments = @('-xmf', $archivePath, '-C', $destinationPath)
        if ($Strip -gt 0) { $arguments += "--strip-components=$Strip" }
        & $systemTar @arguments
        if ($LASTEXITCODE -ne 0) { throw "Could not unpack $(Split-Path -Leaf $archivePath) (Windows tar exit code $LASTEXITCODE)." }
        return
    }

    # ZIP files (including Python wheels) can be extracted without tar or
    # Python, even during the portable toolchain bootstrap.
    if ([IO.Path]::GetExtension($archivePath) -in @('.zip', '.whl')) {
        Add-Type -AssemblyName System.IO.Compression
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $prefix = [IO.Path]::GetFullPath($destinationPath).TrimEnd('\', '/') + '\'
        $zip = [IO.Compression.ZipFile]::OpenRead($archivePath)
        try {
            foreach ($entry in $zip.Entries) {
                $name = $entry.FullName.Replace('\', '/')
                $parts = $name.TrimEnd('/').Split('/')
                if ($name.StartsWith('/')) { throw "Invalid path in archive: $name" }
                foreach ($part in $parts) {
                    if ($part -in @('', '.', '..') -or $part.Contains(':')) {
                        throw "Invalid path in archive: $name"
                    }
                }
                if ($parts.Length -le $Strip) { continue }
                $relative = $parts[$Strip..($parts.Length - 1)] -join '\'
                $target = [IO.Path]::GetFullPath((Join-Path $destinationPath $relative))
                if (!$target.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
                    throw "Invalid path in archive: $name"
                }
                if ($name.EndsWith('/')) {
                    [IO.Directory]::CreateDirectory($target) | Out-Null
                    continue
                }
                [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target)) | Out-Null
                $inputStream = $entry.Open()
                try {
                    $outputStream = [IO.File]::Open($target, [IO.FileMode]::Create)
                    try { $inputStream.CopyTo($outputStream) } finally { $outputStream.Dispose() }
                } finally { $inputStream.Dispose() }
            }
        } finally { $zip.Dispose() }
        return
    }

    # A portable Python installation is already available by the time the
    # .crate and Rust archives are unpacked on older Windows systems.
    $python = Join-Path $ProjectRoot 'build/p/python/python.exe'
    if (!(Test-Path -LiteralPath $python -PathType Leaf)) {
        $python = (Get-Command python.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1).Source
    }
    if (!$python) { throw 'Windows tar is unavailable and Python is required to unpack this TAR archive.' }
    $extract = @'
import sys, tarfile
archive, destination, strip = sys.argv[1:]
strip = int(strip)
def filter_member(member, target):
    parts = member.name.split('/')
    if len(parts) <= strip:
        return None
    return tarfile.data_filter(member.replace(name='/'.join(parts[strip:]), mtime=None, deep=False), target)
with tarfile.open(archive, 'r:*') as t:
    t.extractall(destination, filter=filter_member)
'@
    & $python -c $extract $archivePath $destinationPath "$Strip"
    if ($LASTEXITCODE -ne 0) { throw "Could not unpack $(Split-Path -Leaf $archivePath) with Python." }
}

function Get-Sm3dlVerifiedArchive([string] $Name, [string] $Url, [string] $Sha256, [string] $Directory) {
    $path = Join-Path $Directory $Name
    if (!(Test-Path -LiteralPath $path)) {
        $partial = "$path.partial"
        Write-Host "Downloading $Name"
        & curl.exe --fail --location --silent --show-error --retry 2 --connect-timeout 30 --output $partial $Url
        if ($LASTEXITCODE -ne 0) { throw "Could not download $Name." }
        if ((Get-Sha256 $partial) -ne $Sha256) { throw "SHA-256 mismatch for $Name" }
        Move-Item -LiteralPath $partial -Destination $path
    }
    if ((Get-Sha256 $path) -ne $Sha256) { throw "SHA-256 mismatch for $Name" }
    return $path
}

function Get-Sm3dlBuildDirectory([string] $Configuration, [bool] $Portable) {
    $name = if ($Portable) { "windows-Portable-$Configuration" } else { "windows-$Configuration" }
    Join-Path $ProjectRoot "build/$name"
}

function Build-Sm3dlPortable([string] $Configuration, [string] $Fast) {
    $root = (Join-Path $ProjectRoot 'build/p').Replace('\', '/')
    $cmake = "$root/cmake/bin/cmake.exe"
    $build = Get-Sm3dlBuildDirectory $Configuration $true
    [int]$requested = 0
    $jobs = if ([int]::TryParse($env:CMAKE_BUILD_PARALLEL_LEVEL, [ref] $requested) -and $requested -gt 0) {
        $requested
    } else { 6 }
    $arguments = @(
        '-S', $ProjectRoot, '-B', $build, '-G', 'Ninja',
        "-DCMAKE_BUILD_TYPE=$Configuration",
        "-DCMAKE_MAKE_PROGRAM=$root/ninja/ninja.exe",
        "-DCMAKE_C_COMPILER=$root/llvm/bin/x86_64-w64-mingw32-clang.exe",
        "-DCMAKE_CXX_COMPILER=$root/llvm/bin/x86_64-w64-mingw32-clang++.exe",
        "-DCMAKE_RC_COMPILER=$root/llvm/bin/x86_64-w64-mingw32-windres.exe",
        "-DPython3_EXECUTABLE=$root/python/python.exe",
        "-DSM3DL_FAST_BUILD=$Fast"
    )
    & $cmake @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Could not configure the portable Windows build.' }
    & $cmake --build $build --target SuperMario3DLand --parallel $jobs
    if ($LASTEXITCODE -ne 0) { throw 'Portable Windows compilation failed.' }
}

function Find-Sm3dlVisualStudio {
    $finder = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
    if (!(Test-Path -LiteralPath $finder)) { throw 'Install Visual Studio with the Desktop development with C++ workload.' }
    $instances = & $finder -all -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    foreach ($instance in $instances) {
        $cmake = Join-Path $instance 'Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe'
        $ninja = Join-Path $instance 'Common7/IDE/CommonExtensions/Microsoft/CMake/Ninja/ninja.exe'
        if ((Test-Path -LiteralPath $cmake) -and (Test-Path -LiteralPath $ninja)) { return $instance }
    }
    throw 'Visual Studio with C++ and CMake tools was not found.'
}

function Get-Sm3dlBuildJobs {
    [int] $requested = 0
    if ([int]::TryParse($env:CMAKE_BUILD_PARALLEL_LEVEL, [ref] $requested) -and $requested -gt 0) {
        return $requested
    }

    $processors = [Environment]::ProcessorCount
    try {
        Add-Type -AssemblyName Microsoft.VisualBasic
        $available = (New-Object Microsoft.VisualBasic.Devices.ComputerInfo).AvailablePhysicalMemory
    } catch {
        try {
            $available = [double](Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory * 1KB
        } catch {
            return [Math]::Min($processors, 2)
        }
    }

    # Leave memory for Windows and room for several large generated C files at once.
    $memoryJobs = [Math]::Floor(([double]$available - 2GB) / 2GB)
    return [int][Math]::Max(1, [Math]::Min($processors, $memoryJobs))
}

function Build-Sm3dl([string] $Configuration, [ValidateSet('ON','OFF')] [string] $Fast = 'OFF') {
    $visualStudio = Find-Sm3dlVisualStudio
    $developerPrompt = Join-Path $visualStudio 'Common7/Tools/VsDevCmd.bat'
    $jobs = Get-Sm3dlBuildJobs
    Write-Host "Compiling with $jobs parallel jobs."
    & (Join-Path $PSScriptRoot 'native_build.cmd') $developerPrompt $visualStudio $Configuration $Fast $jobs
    if ($LASTEXITCODE -ne 0) { throw "Windows build failed ($LASTEXITCODE)." }
}


function Get-Sha256([string] $Path) {
    $stream = [IO.File]::OpenRead((Resolve-Path -LiteralPath $Path).Path)
    try {
        $sha = [Security.Cryptography.SHA256]::Create()
        try {
            [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '')
        } finally {
            $sha.Dispose()
        }
    } finally {
        $stream.Dispose()
    }
}
