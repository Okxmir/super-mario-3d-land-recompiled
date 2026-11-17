# Build Super Mario 3D Land recompiled on Windows

Use Windows 10 or 11 x64 and an internet connection for the first build. The portable build downloads its own compiler, Python, and other pinned dependencies. It takes several minutes, depending on your connection and PC.

Use a decrypted `.3ds`, `.cci`, or `.cxi` dump of the supported European revision (`CTR-P-AREP`, title ID `0004000000053F00`). The build verifies the game partition and the unpacked code before generating the native executable.

Open the project folder in File Explorer, type `cmd` in the address bar, and press Enter. Run the build from Command Prompt.

```bat
build.cmd -Portable -Cartridge "C:\Games\Super Mario 3D Land (Europe).3ds" -Language en
```

In PowerShell, use `./build.cmd` with the same arguments. Set `-Language` to `en` (English), `fr` (French), `de` (German), `es` (Spanish), `it` (Italian), `nl` (Dutch), `pt` (Portuguese), or `ru` (Russian). You can rerun the command with another language. The local build keeps the save data in `dist/userdata`.

After the build, open `dist/SuperMario3DLandRecompiled.exe`. Keep the other files in `dist` beside the executable. The **Upscaling** menu offers 1×, 2×, and 4× and saves the selected value in `dist/userdata/settings.ini`.

To use an installed toolchain, omit `-Portable`. This path requires 64-bit Python 3.11 or later with pip and Visual Studio with **Desktop development with C++**, the Windows SDK, and CMake tools. Use `-OutputDirectory` to choose a different destination for either build.

The game uses the original 400 × 240 top screen and 320 × 240 touchscreen. Upscaling multiplies each screen's width and height by the same factor.

The Vulkan renderer targets a 60 Hz refresh for the top screen and keeps the original 30 Hz game logic. It fills the extra refresh with a uniform pixel translation when the camera motion is consistent across the screen. Other movements and cuts use the original image. This can add one display refresh of latency.

Connect a Windows-compatible gamepad and use the left stick to move. Controller mappings follow the positions of the 3DS buttons. On an Xbox controller, **A** jumps, **X** runs, and **Menu** pauses.

On first launch, decline StreetPass to play offline. The profile setup supplies a local Player Mii.
