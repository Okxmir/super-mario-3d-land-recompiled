# Super Mario 3D Land recompiled

An experimental native Windows x64 port of Super Mario 3D Land. It recompiles the European game's ARM code and reads the assets from a local ROM.

## Current features

- Native Windows x64 executable built from the supported European ROM.
- Vulkan rendering with a 60 Hz presentation target and camera-motion smoothing, while preserving the original 30 Hz game logic. Performance depends on the PC and the scene.
- **Upscaling** menu with 1×, 2×, and 4× options and a saved selection between launches.
- **Aspect ratio** menu with Original (5:3), 16:9, and experimental 21:9 options. Its labels follow the selected game language, and the selected format is saved between launches.
- **F9** switches between two stacked screens and the upper game screen enlarged with the touchscreen in an inset. The selected layout is saved between launches.
- Controller and keyboard support, with mouse input for the touchscreen.
- Build-time selection of eight game languages, including English, French, German, Spanish, Italian, Dutch, Portuguese, and Russian.
- Local save data with automatic backups during save formatting.
- One-command portable Windows build that downloads its compiler, Python, and other required tools automatically.
- Build checks for ROM integrity, native startup, textures, display colors, controller input mapping, and screen geometry.

## Future plans

- Add native Linux support.
- Add more features and quality-of-life improvements.

## Build and play

Extract or clone this repository. Open the project folder in File Explorer, type `cmd` in the address bar, and press Enter. Use your own decrypted European ROM (`CTR-P-AREP`) in `.3ds`, `.cci`, or `.cxi` format.

```bat
build.cmd -Portable -Cartridge "YourRom.3ds" -Language en
```

Open `dist/SuperMario3DLandRecompiled.exe` when the build completes. The first build downloads the tools it needs. For the eight language codes and other build options, see the [build guide](BUILD.md).

## Controls and display

Use a Windows-compatible controller or the keyboard. On an Xbox controller, the left stick moves, **A** jumps, **X** runs, and **Menu** pauses. On a QWERTY keyboard use **WASD**, **J** to jump, **U** to run, and **Enter** to pause. Use the mouse on the lower screen.

The **Upscaling** menu offers 1×, 2×, and 4×. Vulkan targets a 60 Hz refresh while keeping the original 30 Hz game logic. A refresh can repeat the original image when camera motion cannot be matched reliably.

Beside **Upscaling**, the **Aspect ratio** menu selects the upper screen's format. With Vulkan, wider formats expand the 3D view and **F7** cycles through the three formats. The lower touchscreen keeps its original 4:3 proportions. The Direct3D 11 fallback uses the original format, with the wider options grayed out.

The 21:9 mode is experimental. Its wider view can reveal scenery edges or objects outside the original camera view.

The aspect ratio applies to the upper game screen. With two stacked screens, the combined window is taller. Press **F9** for the enlarged upper screen with a touchscreen inset, and press **F9** again to restore the stacked screens. Entering the enlarged layout selects the upper screen even when an older setting had swapped the screens.

The title screen, the opening cinematic, the first world map, and early gameplay in course 1-1 have been checked locally. On first launch, decline StreetPass to play offline.

The ROM, compiled game files, and saves remain local. See [LICENSE](LICENSE) and the [third-party license notices](licenses/).
