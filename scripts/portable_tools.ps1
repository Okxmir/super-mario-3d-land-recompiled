function Initialize-Sm3dlPortableTools {
    $root = Join-Path $ProjectRoot 'build/p'
    $downloads = "$root/downloads"
    New-Item -ItemType Directory -Path $downloads -Force | Out-Null

    function Install-Tool($Name, $File, $Url, $Hash, $Marker, [int]$Strip = 0) {
        $target = "$root/$Name"
        $ready = "$target/.ready-$Hash"
        if (!(Test-Path -LiteralPath $ready) -or !(Test-Path -LiteralPath "$target/$Marker" -PathType Leaf)) {
            $archive = Get-Sm3dlVerifiedArchive $File $Url $Hash $downloads
            New-Item -ItemType Directory -Path $target -Force | Out-Null
            & tar.exe -xf $archive -C $target "--strip-components=$Strip"
            if ($LASTEXITCODE -ne 0 -or !(Test-Path -LiteralPath "$target/$Marker" -PathType Leaf)) {
                throw "Could not unpack $File."
            }
            New-Item -ItemType File -Path $ready -Force | Out-Null
        }
    }

    Install-Tool llvm 'llvm-mingw-20260616-ucrt-x86_64.zip' `
        'https://github.com/mstorsjo/llvm-mingw/releases/download/20260616/llvm-mingw-20260616-ucrt-x86_64.zip' `
        'B9B68A4D276E16FA25802AABA458E4638F64B3884C290AACCDC2D87083B6CA35' 'bin/x86_64-w64-mingw32-clang++.exe' 1
    Install-Tool cmake 'cmake-3.31.12-windows-x86_64.zip' `
        'https://github.com/Kitware/CMake/releases/download/v3.31.12/cmake-3.31.12-windows-x86_64.zip' `
        '0C4BAA40F28B3F8225EB3FDF6946C987B4FE901403B4EAF2FBBD9378100AAA0C' 'bin/ctest.exe' 1
    Install-Tool ninja 'ninja-win.zip' 'https://github.com/ninja-build/ninja/releases/download/v1.13.2/ninja-win.zip' `
        '07FC8261B42B20E71D1720B39068C2E14FFCEE6396B76FB7A795FB460B78DC65' 'ninja.exe'
    Install-Tool python 'python-3.13.12-embed-amd64.zip' `
        'https://www.python.org/ftp/python/3.13.12/python-3.13.12-embed-amd64.zip' `
        '76F238F606250C87C6BEAC75DCCD35EE99070A13490555936ABB6CB64ECCE3D0' 'python.exe'

    $python = "$root/python/python.exe"
    @('python313.zip', '.', 'Lib/site-packages', '../../../tools') |
        Set-Content -LiteralPath "$root/python/python313._pth" -Encoding ASCII
    if (!(Test-Path -LiteralPath "$root/python/.modules-ready")) {
        $packages = "$root/python/Lib/site-packages"
        New-Item -ItemType Directory -Path $packages -Force | Out-Null
        $pillow = Get-Sm3dlVerifiedArchive 'pillow-12.2.0-cp313-cp313-win_amd64.whl' `
            'https://files.pythonhosted.org/packages/3f/82/8a3739a5e470b3c6cbb1d21d315800d8e16bff503d1f16b03a4ec3212786/pillow-12.2.0-cp313-cp313-win_amd64.whl' `
            '390EDE346628CCC626E5730107CDE16C42D3836B89662A115A921F28440E6A3B' $downloads
        $png = Get-Sm3dlVerifiedArchive 'pypng-0.20220715.0-py3-none-any.whl' `
            'https://files.pythonhosted.org/packages/3e/b9/3766cc361d93edb2ce81e2e1f87dd98f314d7d513877a342d31b30741680/pypng-0.20220715.0-py3-none-any.whl' `
            '4A43E969B8F5AAAFB2A415536C1A8EC7E341CD6A3F957FD5B5F32A4CFEED902C' $downloads
        foreach ($wheel in @($pillow, $png)) {
            & tar.exe -xf $wheel -C $packages
            if ($LASTEXITCODE -ne 0) { throw "Could not unpack $wheel." }
        }
        & $python -c 'from PIL import Image; import png'
        if ($LASTEXITCODE -ne 0) { throw 'Could not load the portable Python image modules.' }
        New-Item -ItemType File -Path "$root/python/.modules-ready" | Out-Null
    }

    $target = 'x86_64-pc-windows-gnullvm'
    $rust = "1.100.0-$target"
    $rustReady = "$root/rust/.ready-$rust"
    if (!(Test-Path -LiteralPath $rustReady) -or !(Test-Path -LiteralPath "$root/rust/bin/rustc.exe")) {
        $base = 'https://static.rust-lang.org/dist/2026-11-12'
        $compiler = Get-Sm3dlVerifiedArchive "rustc-$rust.tar.xz" "$base/rustc-$rust.tar.xz" `
            '1D4F93B7264C098BF90C86B48B7953A9009F7DC01E4C2BDC8BA30D9407ED47D9' $downloads
        $standardLibrary = Get-Sm3dlVerifiedArchive "rust-std-$rust.tar.xz" "$base/rust-std-$rust.tar.xz" `
            '5E63B95C73BD783864B4350792C27292D67AAB8E3033BF49381D0E55EF4384CF' $downloads
        New-Item -ItemType Directory -Path "$root/rust" -Force | Out-Null
        # Some Windows tar versions delegate .xz decompression to an external xz.exe.
        $extractRustComponent = @'
import sys
import tarfile

archive, destination, component = sys.argv[1:]
prefix = component + '/'

def strip_component(member, target):
    if member.name.startswith(prefix) and member.name != prefix:
        relative = member.replace(name=member.name[len(prefix):], deep=False)
        return tarfile.data_filter(relative, target)
    return None

with tarfile.open(archive, 'r|xz', stream=True) as package:
    package.extractall(destination, filter=strip_component)
'@
        & $python -c $extractRustComponent $compiler "$root/rust" "rustc-$rust/rustc"
        if ($LASTEXITCODE -ne 0 -or !(Test-Path -LiteralPath "$root/rust/bin/rustc.exe" -PathType Leaf)) {
            throw 'Could not unpack portable Rust.'
        }
        & $python -c $extractRustComponent $standardLibrary "$root/rust" "rust-std-$rust/rust-std-$target"
        if ($LASTEXITCODE -ne 0 -or !(Test-Path -LiteralPath "$root/rust/lib/rustlib/$target/lib" -PathType Container)) {
            throw 'Could not unpack the portable Rust standard library.'
        }
        New-Item -ItemType File -Path $rustReady -Force | Out-Null
    }

    # Explicit tools and bundled MinGW headers keep the build independent of VS developer shells.
    foreach ($name in @('INCLUDE', 'LIB', 'LIBPATH', 'CC', 'CXX', 'CFLAGS', 'CXXFLAGS', 'LDFLAGS', 'CMAKE_TOOLCHAIN_FILE')) {
        Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
    }
    $env:Path = "$root/python;$root/llvm/bin;$root/ninja;$root/cmake/bin;$env:Path"
    Write-Host 'Using portable LLVM, CMake, Ninja, Rust and Python.'
}
