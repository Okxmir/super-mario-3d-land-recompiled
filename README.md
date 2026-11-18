# Super Mario 3D Land recompiled

An experimental native Windows x64 and Linux x86-64 port of Super Mario 3D Land. It recompiles the European game's ARM code and reads the assets from a local ROM.

## Current features

- Native Windows x64 and Linux x86-64 executables built from the supported European ROM.
- Vulkan rendering with a 60 Hz presentation target and camera-motion smoothing, while preserving the original 30 Hz game logic. Performance depends on the PC and the scene.
- 1×, 2×, and 4× upscaling with a saved selection. Use the **Upscaling** menu on Windows or **F4** on Linux.
- Original (5:3), 16:9, and experimental 21:9 aspect ratios. Use **F7** or the localized **Aspect ratio** menu on Windows. The selected format is saved between launches.
- **Widescreen** or **F9** enlarges the upper screen. During a course, Vulkan displays the three Star Medals, reserve item and lives between the coin counter and timer, with the course label in the bottom-right corner. Use **R3** or **Tab** to switch between these indicators and the touchscreen inset.
- Controller and keyboard support, with mouse input for the touchscreen.
- Build-time selection of eight game languages, including English, French, German, Spanish, Italian, Dutch, Portuguese, and Russian.
- Local save data with automatic backups during save formatting.
- One-command portable Windows build that downloads its compiler, Python, and other required tools automatically.
- One-command Linux build and a graphical Linux builder with a ROM picker, language selection, and build progress.
- Build checks for ROM integrity, native startup, textures, display colors, controller input mapping, and screen geometry.

## Future plans

- Add more features and quality-of-life improvements.

## Build and play

Extract or clone this repository. Use your own decrypted European ROM (`CTR-P-AREP`) in `.3ds`, `.cci`, or `.cxi` format.

### Windows x64

Open the project folder in File Explorer, type `cmd` in the address bar, and press Enter.

```bat
build.cmd -Portable -Cartridge "YourRom.3ds" -Language en
```

Open `dist/SuperMario3DLandRecompiled.exe` when the build completes. The first build downloads the tools it needs. For the eight language codes and other build options, see the [build guide](BUILD.md).

### Linux x86-64

Install the Linux dependencies in the [build guide](BUILD.md#linux-x86-64), open a terminal in the project folder, and run the following commands.

```bash
bash build.sh --cartridge "YourRom.3ds" --language en
./dist/linux-x64/SuperMario3DLandRecompiled
```

For the graphical builder, run `bash SuperMario3DLandBuilder`. It creates the game folder beside the selected ROM. Open it again to launch the game. Run `bash SuperMario3DLandBuilder --build-menu` to return to the setup menu.

## Controls and display

Use an SDL-compatible controller or the keyboard. On an Xbox controller, the left stick moves, **A** jumps, **X** runs, and **Menu** pauses. On a QWERTY keyboard use **WASD**, **J** to jump, **U** to run, and **Enter** to pause. Use the mouse on the lower screen.

Use the Windows **Upscaling** menu or **F4** on Linux to select 1×, 2×, or 4×. Vulkan targets a 60 Hz refresh while keeping the original 30 Hz game logic. A refresh can repeat the original image when camera motion cannot be matched reliably.

With Vulkan, wider formats expand the 3D view and **F7** cycles through the three formats. The Windows **Aspect ratio** menu selects the same formats. The lower touchscreen keeps its original 4:3 proportions. The fallback renderer uses the original format.

The 21:9 mode is experimental. Its wider view can reveal scenery edges or objects outside the original camera view.

The aspect ratio applies to the upper game screen. Click **Widescreen** below **Original** in the **Aspect ratio** menu, or press **F9**, to show the upper screen by itself. Click the right stick (**R3**) or press **Tab** to hide the extra course indicators and show the interactive touchscreen inset in the bottom-right corner. Use **R3** or **Tab** again to hide the inset and bring back the indicators. **F9** or **Widescreen** restores the stacked layout. The layout is saved between launches, and the menu label follows the game language.

The title screen, the opening cinematic, the first world map, and early gameplay in course 1-1 have been checked locally. On first launch, decline StreetPass to play offline.

The ROM, compiled game files, and saves remain local. See [LICENSE](LICENSE) and the [third-party license notices](licenses/).
