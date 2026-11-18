# Build Super Mario 3D Land recompiled

## Windows x64

Use Windows 10 or 11 x64 and an internet connection for the first build. The portable build downloads its own compiler, Python, and other pinned dependencies. It takes several minutes, depending on your connection and PC.

Use a decrypted `.3ds`, `.cci`, or `.cxi` dump of the supported European revision (`CTR-P-AREP`, title ID `0004000000053F00`). The build verifies the game partition and the unpacked code before generating the native executable.

The builder identifies the supported original revision from the game code. It verifies the decrypted content even if the container still reports encryption. When the full ExHeader matches the supported original, the extractor can restore its digest in the generated build copy. The input ROM stays on disk as supplied. Revisions with different game code require a separate port update.

Open the project folder in File Explorer, type `cmd` in the address bar, and press Enter. Run the build from Command Prompt.

```bat
build.cmd -Portable -Cartridge "C:\Games\Super Mario 3D Land (Europe).3ds" -Language en
```

In PowerShell, use `./build.cmd` with the same arguments. Set `-Language` to `en` (English), `fr` (French), `de` (German), `es` (Spanish), `it` (Italian), `nl` (Dutch), `pt` (Portuguese), or `ru` (Russian). You can rerun the command with another language. The local build keeps the save data in `dist/userdata`.

After the build, open `dist/SuperMario3DLandRecompiled.exe`. Keep the other files in `dist` beside the executable. The **Upscaling** menu offers 1×, 2×, and 4× and saves the selected value in `dist/userdata/settings.ini`.

The **Aspect ratio** menu beside **Upscaling** offers Original (5:3), 16:9, and 21:9 for the upper screen. Its labels use the language selected with `-Language`. The choice is saved in `dist/userdata/settings.ini` as `aspect_ratio=0`, `1`, or `2`. **F7** cycles through the formats. The touchscreen keeps its original proportions in every format.

The 21:9 option is marked experimental because the expanded view can reveal scenery edges or objects outside the original camera view.

The 16:9 and 21:9 options require Vulkan. With the Direct3D 11 fallback, the game uses the original format and disables the wider menu options. A saved widescreen preference is kept for the next Vulkan launch.

The selected ratio applies to the upper game screen. Click **Widescreen** directly below **Original** in the **Aspect ratio** menu, or press **F9**, to switch from two stacked screens to the enlarged upper screen. With Vulkan, the course HUD shows the Star Medals, reserve item and lives along the top and the course label in the bottom-right corner. **R3** or **Tab** replaces those indicators with the touchscreen inset in the bottom-right corner, and pressing it again restores the indicators. Use **Widescreen** or **F9** again to restore the stacked layout. The menu label follows the chosen game language. The layout is saved between launches. The 16:9 display uses an exact 1280 × 720 logical canvas in the enlarged layout, with a centered crop of the slightly wider GPU render target.

To use an installed toolchain, omit `-Portable`. This path requires 64-bit Python 3.11 or later with pip and Visual Studio with **Desktop development with C++**, the Windows SDK, and CMake tools. Use `-OutputDirectory` to choose a different destination for either build.

The game uses the original 400 × 240 top screen and 320 × 240 touchscreen. Upscaling multiplies each screen's width and height by the same factor.

The Vulkan renderer targets a 60 Hz refresh for the top screen and keeps the original 30 Hz game logic. It fills the extra refresh with a uniform pixel translation when the camera motion is consistent across the screen. Other movements and cuts use the original image. This can add one display refresh of latency.

Connect a Windows-compatible gamepad and use the left stick to move. Controller mappings follow the positions of the 3DS buttons. On an Xbox controller, **A** jumps, **X** runs, and **Menu** pauses.

On first launch, decline StreetPass to play offline. The profile setup supplies a local Player Mii.

## Linux x86-64

Use a C++20 compiler, CMake 3.24 or newer, Ninja, Python 3.11 or newer with Pillow and PyPNG, and Rust 1.90 or newer with Cargo. The first build downloads pinned dependencies. Install the packages below on Ubuntu 24.04 or use your distribution's equivalents.

```bash
sudo apt update
sudo apt install build-essential cmake ninja-build pkg-config ca-certificates \
  python3 python3-pil python3-png python3-tk libssl-dev libx11-dev libxext-dev \
  libxrandr-dev libxi-dev libxcursor-dev libxfixes-dev libxss-dev libxtst-dev \
  libxkbcommon-dev libwayland-dev libegl-dev libdecor-0-dev libasound2-dev \
  libpulse-dev libvulkan-dev
```

Use [rustup](https://rustup.rs/) if your distribution's Rust version is older than 1.90. Install the Vulkan driver for your GPU for hardware rendering.

Open a terminal in the project folder and run the build using a decrypted European ROM (`CTR-P-AREP`) in `.3ds`, `.cci`, or `.cxi` format.

```bash
bash build.sh --cartridge "YourRom.3ds" --language en
./dist/linux-x64/SuperMario3DLandRecompiled
```

Use `--language en`, `fr`, `de`, `es`, `it`, `nl`, `pt`, or `ru`. Omit the option to keep a saved language preference. The build runs the same six tests as the Windows build. It writes the executable and required local files to `dist/linux-x64`. Keep the files together. Saves and display preferences are stored in `userdata` beside the executable.

For the graphical builder, run `bash SuperMario3DLandBuilder` from the project or extracted builder folder. Choose the ROM and language, then click **Build**. The builder shows progress and estimates the remaining time once enough compilation steps have finished. When the build completes, run the builder again to launch the game. Use `bash SuperMario3DLandBuilder --build-menu` to return to the ROM and language selector. The game directory is created beside the ROM. The builder writes a log to `build/linux-builder.log`.

Each build uses up to four parallel compile jobs by default. Set `CMAKE_BUILD_PARALLEL_LEVEL=2` if you need to reduce compiler memory use. **F4** cycles through the upscaling options with Vulkan, **F7** switches aspect ratios, and **F9** switches the upper-screen layout.

## Optional HD textures

The graphical Windows and Linux builders download and install the [1080p texture pack by Henriko Magnifico](https://www.henrikomagnifico.com/super-mario-3d-land-hd) when **Install HD textures (1080p, 107 MB)** is checked. The box starts checked. Clear it to build without the download. If the download fails, the builder finishes with the original textures and shows a message.

For an existing command-line build, run `python tools/hd_pack.py dist` on Windows or `python3 tools/hd_pack.py dist/linux-x64` on Linux. Use the folder containing the game executable if you built to a custom location. The installer extracts only the texture PNGs. With Vulkan, use **HD** next to **Aspect ratio** on Windows or **Ctrl+F10** on Linux to toggle the pack.
