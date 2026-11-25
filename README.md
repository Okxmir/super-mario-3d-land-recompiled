# Super Mario 3D Land recompiled

An experimental native Windows x64 and Linux x86-64 port of Super Mario 3D Land. It recompiles the European game's ARM code and reads the assets from a local ROM.

## Current features

- Native Windows x64 and Linux x86-64 executables built from the supported European ROM.
- Original 30 Hz gameplay, with a saved choice of original 30 FPS rendering or native ARM rendering targeting 60 FPS on the upper screen. Restart to apply the FPS selection.
- 1×, 2×, and 4× upscaling with a saved selection. Use the **Upscaling** menu on Windows or **F4** on Linux.
- Optional [1080p and 4K texture packs by Henriko Magnifico](https://www.henrikomagnifico.com/super-mario-3d-land-hd). The graphical builders offer separate checkboxes. The 1080p box starts checked; 4K is opt-in. With Vulkan, choose **None**, **1080p**, or **4K** from **HD** on Windows, or cycle through installed packs with **Ctrl+F10** on Linux.
  For a [manual install](BUILD.md#manual-texture-installation), put the extracted texture PNGs in `userdata/hd-textures/sm3dl-1080p-1.2.0b/` or `userdata/hd-textures/sm3dl-4k-1.2.0b/` beside the game executable. In-game HD options are available only for complete packs.
- The mouse cursor hides over the game after seven seconds of inactivity and reappears when the mouse moves or clicks.
- Original (5:3), 16:9, and experimental 21:9 aspect ratios. Use **F7** or the localized **Aspect ratio** menu on Windows. The selected format is saved between launches.
- Maximizing **16:9 Widescreen** extends the 3D view to fill the wider window while keeping the title bar and menus visible. **F11** switches to exact 16:9 fullscreen without bars on a 16:9 display, without stretching the image.
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

Install the system dependencies in the [build guide](BUILD.md#linux-x86-64). Rust and Cargo are set up automatically if needed. For a Git checkout, open a terminal in the project folder and run:

```bash
bash build.sh --cartridge "YourRom.3ds" --language en &&
./dist/linux-x64/SuperMario3DLandRecompiled
```

For the graphical launcher, extract the Linux `.tar.gz` with its folders intact, then run `bash SuperMario3DLandBuilder` from the extracted directory or a Git checkout. Pick your ROM, language and optional HD packs, then choose **Build** and **Play**. The launcher keeps its files in `LauncherData`. The [launcher guide](launcher/README.md) covers Windows and Linux setup, controls, saves and updates.

## Display

Use the Windows **Upscaling** menu or **F4** on Linux to select 1×, 2×, or 4×. Use **FPS** on Windows or **Ctrl+F6** to choose the original 30 FPS mode or the patched 60 FPS mode, then restart the game. Both modes use the original 30 Hz physics and countdown and share the same saves. The 60 FPS mode uses the patch's additional render phases and a short Vulkan presentation queue, not PC-side interpolation. Actual frame rate depends on the scene and PC. These modes do not change the touchscreen refresh rate.

Both builders download and verify the upstream ARM patch, adapt it for the supported European revision, and recompile it locally. No USA ROM, Azahar installation, or separate patch installer is needed. The original ROM is not modified.

With Vulkan, wider formats expand the 3D view and **F7** cycles through the three formats. The Windows **Aspect ratio** menu selects the same formats. In **16:9**, the opening cutscene fills the upper screen without its original cinematic matte. No stretching or cropping is applied. The lower touchscreen keeps its original 4:3 proportions. The fallback renderer uses the original format.

The 21:9 mode is experimental. Its wider view can reveal scenery edges or objects outside the original camera view.

The aspect ratio applies to the upper game screen. Click **Widescreen** below **Original** in the **Aspect ratio** menu, or press **F9**, to show the upper screen by itself. Widescreen selects **16:9** when switching from **Original** and leaves **21:9** selected if you already use it. Click the right stick (**R3**) or press **Tab** to hide the extra course indicators and show the interactive touchscreen inset in the bottom-right corner. Use **R3** or **Tab** again to hide the inset and bring back the indicators. **F9** or **Widescreen** restores the stacked layout. The layout is saved between launches, and the menu label follows the game language.

The game opens directly at the title screen without the first-launch StreetPass setup. Press **A** to select a save file. The title screen, the opening cinematic, the first world map, and early gameplay in course 1-1 have been checked locally.

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
| Use the reserve item during a course | **Up arrow** or click the reserve slot | **D-pad Up** | **D-pad Up** |
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
| **Ctrl+F10** (Linux) / **HD** menu (Windows) | Choose original textures or an installed HD pack with Vulkan |
| **Ctrl+F6** / **FPS** menu (Windows) | Save the 30 or 60 FPS selection for the next launch |
| **F10** | Start or stop texture dumping |
| **F12** / **Shift+F12** | Save a screenshot and diagnostics / capture a short frame sequence |
