# Super Mario 3D Land recompiled

An experimental native Windows x64 and Linux x86-64 port of Super Mario 3D Land. It recompiles the European game's ARM code and reads the assets from a local ROM.

## Current features

- Native Windows x64 and Linux x86-64 executables built from the supported European ROM.
- Experimental **native 60 Hz course logic** is enabled by default with Vulkan. Retimed movement, collision, camera and object states use smaller steps to preserve their original speed. Other states and cutscenes retain their original timing. Not every course or interaction is verified yet. Use `--original-30hz` to restore the previous mode.
- 1×, 2×, and 4× upscaling with a saved selection. Use the **Upscaling** menu on Windows or **F4** on Linux.
- Optional [1080p texture pack by Henriko Magnifico](https://www.henrikomagnifico.com/super-mario-3d-land-hd). The graphical builders download and install it during the build when **Install HD textures** is checked. The option starts checked. With Vulkan, click **HD** on Windows or use **Ctrl+F10** on Linux to switch textures while playing.
- Original (5:3), 16:9, and experimental 21:9 aspect ratios. Use **F7** or the localized **Aspect ratio** menu on Windows. The selected format is saved between launches.
- Maximizing **16:9 Widescreen** extends the 3D view to fill the wider window while keeping the title bar and menus visible. **F11** toggles fullscreen separately.
- **Widescreen** or **F9** enlarges the upper screen. During a course, Vulkan displays the three Star Medals, reserve item and lives between the coin counter and timer, with the course label in the bottom-right corner. Use **R3** or **Tab** to switch between these indicators and the touchscreen inset.
- In Widescreen with the touchscreen hidden, the pause buttons and confirmation dialogs appear in the center. The HD pack also sharpens the English and French pause labels.
- Controller and keyboard support, with mouse input for the touchscreen. D-pad Up uses the reserve item during a course, even when the touchscreen is hidden.
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

## Display

Use the Windows **Upscaling** menu or **F4** on Linux to select 1×, 2×, or 4×. Vulkan enables the experimental native course logic by default. The game does not interpolate frames while native 60 Hz logic is running. Original-rate sections may still use camera-motion smoothing.

To use the original 30 Hz logic with the previous Vulkan presentation mode, run the built executable with `--original-30hz`. From the project folder:

```bat
dist\SuperMario3DLandRecompiled.exe --original-30hz
```

```bash
./dist/linux-x64/SuperMario3DLandRecompiled --original-30hz
```

The option applies to that launch only. Native 60 Hz logic needs Vulkan; the fallback renderer uses the original game cadence. Some object states (including the small bird's flight and Bob-omb walking) still run at 30 Hz in the experimental mode. Performance depends on the scene and PC, and timing is not yet verified throughout the game.

With Vulkan, wider formats expand the 3D view and **F7** cycles through the three formats. The Windows **Aspect ratio** menu selects the same formats. The lower touchscreen keeps its original 4:3 proportions. The fallback renderer uses the original format.

The 21:9 mode is experimental. Its wider view can reveal scenery edges or objects outside the original camera view.

The aspect ratio applies to the upper game screen. Click **Widescreen** below **Original** in the **Aspect ratio** menu, or press **F9**, to show the upper screen by itself. Click the right stick (**R3**) or press **Tab** to hide the extra course indicators and show the interactive touchscreen inset in the bottom-right corner. Use **R3** or **Tab** again to hide the inset and bring back the indicators. **F9** or **Widescreen** restores the stacked layout. The layout is saved between launches, and the menu label follows the game language.

The title screen, the opening cinematic, the first world map, and early gameplay in course 1-1 have been checked locally. On first launch, decline StreetPass to play offline.

The ROM, compiled game files, and saves remain local. See [LICENSE](LICENSE) and the [third-party license notices](licenses/).

## Default controls

Keyboard bindings are shown for QWERTY and follow physical key positions. Use an SDL-compatible controller; the face buttons are mapped by position, not by their printed letters.

| Game input | Keyboard / mouse | Xbox controller | PlayStation controller |
| --- | --- | --- | --- |
| Move (Circle Pad) | **W / A / S / D** | Left stick | Left stick |
| Jump (3DS B) | **J** | **A** | **Cross** |
| Run (3DS Y) | **U** | **X** | **Square** |
| 3DS A | **K** | **B** | **Circle** |
| 3DS X | **I** | **Y** | **Triangle** |
| 3DS L / R | **Q / E** | **LB / RB** | **L1 / R1** |
| 3DS ZL / ZR input | **1 / 3** | **LT / RT** | **L2 / R2** |
| Pause (Start) | **Enter** | **Menu** | **Options** |
| Select | **Backspace** | **View** | **Share / Create** |
| 3DS D-pad | **Arrow keys** | D-pad | D-pad |
| Use the reserve item during a course | Click its slot on the touchscreen | **D-pad Up** | **D-pad Up** |
| Touchscreen | Left mouse button on the lower screen or its inset | — | — |
| Show or hide the touchscreen inset in Widescreen | **Tab** | **R3** (press the right stick) | **R3** (press the right stick) |

| Display shortcut | Action |
| --- | --- |
| **F4** (Linux) / **Upscaling** menu (Windows) | Cycle or select 1×, 2× or 4× |
| **F7** / **Aspect ratio** menu (Windows) | Cycle or select Original, 16:9 or 21:9 with Vulkan |
| **F9** / **Widescreen** menu item (Windows) | Switch between stacked screens and the upper-screen layout |
| **F8** | Toggle the secondary-screen inset |
| **F6** / **F5** | Toggle the adaptive layout / cycle its layout for the current scene |
| **F11** | Toggle fullscreen manually |
| **Ctrl+F10** (Linux) / **HD** button (Windows) | Toggle the installed HD pack with Vulkan |
| **F10** | Start or stop texture dumping |
| **F12** / **Shift+F12** | Save a screenshot and diagnostics / capture a short frame sequence |
