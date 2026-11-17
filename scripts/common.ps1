$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot

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
