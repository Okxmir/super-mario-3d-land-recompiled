# Super Mario 3D Land recompiled

An experimental native Windows x64 port of Super Mario 3D Land. It recompiles the European game's ARM code and reads the assets from a local ROM.

## Build and play

Extract or clone this repository. Open the project folder in File Explorer, type `cmd` in the address bar, and press Enter. Use your own decrypted European ROM (`CTR-P-AREP`) in `.3ds`, `.cci`, or `.cxi` format.

```bat
build.cmd -Portable -Cartridge "YourRom.3ds" -Language en
```

Open `dist/SuperMario3DLandRecompiled.exe` when the build completes. The first build downloads the tools it needs. For the eight language codes and other build options, see the [build guide](BUILD.md).

## Controls and display

Use a Windows-compatible controller or the keyboard. On an Xbox controller, the left stick moves, **A** jumps, **X** runs, and **Menu** pauses. On a QWERTY keyboard use **WASD**, **J** to jump, **U** to run, and **Enter** to pause. Use the mouse on the lower screen.

The **Upscaling** menu offers 1×, 2×, and 4×. Vulkan targets a 60 Hz refresh while keeping the original 30 Hz game logic. A refresh can repeat the original image when camera motion cannot be matched reliably.

The title screen, the opening cinematic, the first world map, and early gameplay in course 1-1 have been checked locally. On first launch, decline StreetPass to play offline.

The ROM, compiled game files, and saves remain local. See [LICENSE](LICENSE) and the [third-party license notices](licenses/).
