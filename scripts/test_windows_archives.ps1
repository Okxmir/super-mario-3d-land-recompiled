param([switch] $RealArchives)
. "$PSScriptRoot/common.ps1"

$root = Join-Path $ProjectRoot ('build/archive-regression-' + [Guid]::NewGuid().ToString('N'))
$previousPath = $env:Path
try {
    $shadow = Join-Path $root 'DevkitPro simulation'
    $destination = Join-Path $root 'Recomp Library/source with spaces'
    New-Item -ItemType Directory -Path $shadow, $destination -Force | Out-Null
    # A wrong tar.exe at the front of PATH must never be invoked.
    Copy-Item -LiteralPath (Join-Path $env:SystemRoot 'System32/where.exe') -Destination (Join-Path $shadow 'tar.exe')
    $env:Path = "$shadow;$previousPath"
    $resolvedShadow = (Get-Item -LiteralPath (Join-Path $shadow 'tar.exe')).FullName
    $pathTar = (Get-Command tar.exe -CommandType Application -All | Select-Object -First 1).Source
    if ($pathTar -ne $resolvedShadow) {
        throw "The PATH collision fixture was not installed: $pathTar instead of $resolvedShadow."
    }

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = Join-Path $root 'test archive.zip'
    $zip = [IO.Compression.ZipFile]::Open($archive, [IO.Compression.ZipArchiveMode]::Create)
    try {
        $entry = $zip.CreateEntry('tool/bin/file.txt')
        $writer = New-Object IO.StreamWriter($entry.Open())
        try { $writer.Write('portable tool') } finally { $writer.Dispose() }
    } finally { $zip.Dispose() }

    Expand-Sm3dlArchive $archive $destination 1
    if ((Get-Content -LiteralPath "$destination/bin/file.txt" -Raw) -ne 'portable tool') {
        throw 'The native Windows archive extractor did not strip the archive root.'
    }
    Write-Host 'PASS: native extraction with a conflicting tar.exe on PATH and spaces in both paths.'

    if ($RealArchives) {
        $downloads = Join-Path $ProjectRoot 'build/p/downloads'
        $cases = @(
            @('llvm-mingw-20260616-ucrt-x86_64.zip', 'llvm', 'bin/x86_64-w64-mingw32-clang++.exe', 1),
            @('cmake-3.31.12-windows-x86_64.zip', 'cmake', 'bin/ctest.exe', 1),
            @('ninja-win.zip', 'ninja', 'ninja.exe', 0),
            @('python-3.13.12-embed-amd64.zip', 'python', 'python.exe', 0),
            @('pillow-12.2.0-cp313-cp313-win_amd64.whl', 'pillow', 'PIL/Image.py', 0),
            @('pypng-0.20220715.0-py3-none-any.whl', 'pypng', 'png.py', 0)
        )
        foreach ($case in $cases) {
            $target = Join-Path $destination $case[1]
            Expand-Sm3dlArchive (Join-Path $downloads $case[0]) $target ([int]$case[3])
            if (!(Test-Path -LiteralPath (Join-Path $target $case[2]) -PathType Leaf)) {
                throw "Missing extracted file: $($case[2])"
            }
            Write-Host "PASS: $($case[0])"
        }
        Expand-Sm3dlArchive (Join-Path $ProjectRoot 'build/upstream/memmap2-0.9.11.crate') "$destination/crate"
        if (!(Test-Path -LiteralPath "$destination/crate/memmap2-0.9.11/Cargo.toml" -PathType Leaf)) {
            throw 'Missing extracted Rust crate.'
        }
        & "$destination/llvm/bin/x86_64-w64-mingw32-clang++.exe" --version
        if ($LASTEXITCODE -ne 0) { throw 'Extracted LLVM compiler could not run.' }
        & "$destination/ninja/ninja.exe" --version
        if ($LASTEXITCODE -ne 0) { throw 'Extracted Ninja could not run.' }
    }

    # Simulate a Windows installation without the built-in tar executable.
    function Get-Sm3dlSystemTar { return $null }
    $fallback = Join-Path $root 'ZIP fallback with spaces'
    Expand-Sm3dlArchive $archive $fallback 1
    if ((Get-Content -LiteralPath "$fallback/bin/file.txt" -Raw) -ne 'portable tool') {
        throw 'The .NET ZIP fallback did not strip the archive root.'
    }
    Write-Host 'PASS: native .NET ZIP fallback without tar.'
    if ($RealArchives) {
        Expand-Sm3dlArchive (Join-Path $ProjectRoot 'build/upstream/memmap2-0.9.11.crate') "$fallback/crate"
        if (!(Test-Path -LiteralPath "$fallback/crate/memmap2-0.9.11/Cargo.toml" -PathType Leaf)) {
            throw 'The Python TAR fallback did not extract the Rust crate.'
        }
        Write-Host 'PASS: Python TAR fallback without Windows tar.'
    }
} finally {
    $env:Path = $previousPath
    if (Test-Path -LiteralPath $root) {
        $resolved = (Resolve-Path -LiteralPath $root).Path
        $expected = (Join-Path $ProjectRoot 'build/archive-regression-')
        if ($resolved.StartsWith($expected, [StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $resolved -Recurse -Force
        }
    }
}
