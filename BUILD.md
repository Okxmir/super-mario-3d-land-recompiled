# Build Super Mario 3D Land recompiled

## Windows x64

Use Windows 10 or 11 x64 and an internet connection for the first build. The portable build downloads its own compiler, Python, and other pinned dependencies. It takes several minutes, depending on your connection and PC.

Use a decrypted `.3ds`, `.cci`, or `.cxi` dump of the supported European revision (`CTR-P-AREP`, title ID `0004000000053F00`). The build verifies the game partition and the unpacked code before generating the native executable.

The builder identifies the supported original revision from the game code. It verifies the decrypted content even if the container still reports encryption. When the full ExHeader matches the supported original, the extractor can restore its digest in the generated build copy. The input ROM stays on disk as supplied. Revisions with different game code require a separate port update.

The first build downloads the [upstream 0.2-preview ARM patch](https://github.com/AlonBorodAHub/mario-3d-land-60fps/tree/eab11f6cc03c9df6ba06cd56af1ac28e7cf64a09/patch) and checks its SHA-256. The build relocates it for the European ROM before generating native code. You do not need the USA ROM, Azahar, or the upstream installer. No patch or game data is bundled in the builders.

Open the project folder in File Explorer, type `cmd` in the address bar, and press Enter. Run the build from Command Prompt.

```bat
build.cmd -Portable -Cartridge "C:\Games\Super Mario 3D Land (Europe).3ds" -Language en
```

In PowerShell, use `./build.cmd` with the same arguments. Set `-Language` to `en` (English), `fr` (French), `de` (German), `es` (Spanish), `it` (Italian), `nl` (Dutch), `pt` (Portuguese), or `ru` (Russian). You can rerun the command with another language. The local build keeps the save data in `dist/userdata`.

After the build, open `dist/SuperMario3DLandRecompiled.exe`. Keep the other files in `dist` beside the executable. The **Upscaling** menu offers 1×, 2×, and 4× and saves the selected value in `dist/userdata/settings.ini`.

The **Aspect ratio** menu offers Original (5:3), 16:9, and 21:9 for the upper screen. Its labels use the language selected with `-Language`. The choice is saved in `dist/userdata/settings.ini` as `aspect_ratio=0`, `1`, or `2`. **F7** cycles through the formats. The touchscreen keeps its original proportions in every format.

In **Widescreen** (F9) at **16:9**, the game keeps a 16:9 content area in a restored window. If the maximized window's content area is slightly wider, the 3D view extends to both sides without hiding the title bar or menus. **F11** still toggles fullscreen manually.

The 21:9 option is marked experimental because the expanded view can reveal scenery edges or objects outside the original camera view.

The 16:9 and 21:9 options require Vulkan. With the Direct3D 11 fallback, the game uses the original format and disables the wider menu options. A saved widescreen preference is kept for the next Vulkan launch.

The selected ratio applies to the upper game screen. Click **Widescreen** directly below **Original** in the **Aspect ratio** menu, or press **F9**, to switch from two stacked screens to the enlarged upper screen. With Vulkan, the course HUD shows the Star Medals, reserve item and lives along the top and the course label in the bottom-right corner. **R3** or **Tab** replaces those indicators with the touchscreen inset in the bottom-right corner, and pressing it again restores the indicators. Use **Widescreen** or **F9** again to restore the stacked layout. The menu label follows the chosen game language. The layout is saved between launches. The 16:9 display uses an exact 1280 × 720 logical canvas in the enlarged layout, with a centered crop of the slightly wider GPU render target.

To use an installed toolchain, omit `-Portable`. This path requires 64-bit Python 3.11 or later with pip and Visual Studio with **Desktop development with C++**, the Windows SDK, and CMake tools. Use `-OutputDirectory` to choose a different destination for either build.

The game uses the original 400 × 240 top screen and 320 × 240 touchscreen. Upscaling multiplies each screen's width and height by the same factor.

The game runs at its original 30 Hz logic. The **FPS** menu on Windows or **Ctrl+F6** chooses original 30 FPS rendering or the 60 FPS ARM patch. Restart to apply the choice. In 16:9 Widescreen, **F11** fills a 16:9 display without stretching the image or keeping the wider crop used for the maximized window.

Connect a gamepad and use the left stick to move. Controller mappings follow the positions of the 3DS buttons. On an Xbox controller, **A** jumps, **X** runs, and **Menu** pauses. Press **D-pad Up** or the keyboard's **Up arrow** once in a course to use the reserve item in any screen layout.

The game opens directly at the title screen without the StreetPass setup. The profile supplies a local Player Mii.

## Linux x86-64

Use a C++20 compiler, CMake 3.24 or newer, Ninja, and Python 3.11 or newer with Pillow and PyPNG. If a working Rust and Cargo 1.90+ are not already available, the builder downloads and verifies a local copy of both. There is no need to install Rust yourself, use `rustup`, or put `cargo` in `tools`. The first build needs internet access. Install the other packages below on Ubuntu 24.04, or use your distribution's equivalents.

```bash
sudo apt update
sudo apt install build-essential cmake ninja-build pkg-config ca-certificates \
  python3 python3-pil python3-png python3-tk libssl-dev libx11-dev libxext-dev \
  libxrandr-dev libxi-dev libxcursor-dev libxfixes-dev libxss-dev libxtst-dev \
  libxkbcommon-dev libwayland-dev libegl-dev libdecor-0-dev libasound2-dev \
  libpulse-dev libvulkan-dev
```

Install the Vulkan driver for your GPU for hardware rendering.

Open a terminal in the project folder and run the build using a decrypted European ROM (`CTR-P-AREP`) in `.3ds`, `.cci`, or `.cxi` format.

```bash
bash build.sh --cartridge "YourRom.3ds" --language en &&
./dist/linux-x64/SuperMario3DLandRecompiled
```

Use `--language en`, `fr`, `de`, `es`, `it`, `nl`, `pt`, or `ru`. Omit the option to keep a saved language preference. The build runs the same tests as the Windows build. It writes the executable and required local files to `dist/linux-x64`. Keep the files together. Saves and display preferences are stored in `userdata` beside the executable.

For the graphical builder, extract the whole Linux `.tar.gz` using **Extract Here** or `tar -xzf Super-Mario-3D-Land-Linux-x64-Builder.tar.gz`. Leave `source/` beside `SuperMario3DLandBuilder`. Run `bash SuperMario3DLandBuilder` from that folder (or from a Git checkout). Choose the ROM, language and optional texture packs, then click **Build**. Once the system packages above are installed, the builder handles the rest: you do not need to run the terminal build separately. Paths containing spaces, such as `Super Mario 3D Land`, are supported. When the build completes, run the builder again to launch the game. Use `bash SuperMario3DLandBuilder --build-menu` to return to setup. The game directory is created beside the ROM. The builder writes a log to `source/build/linux-builder.log` (or `build/linux-builder.log` in a Git checkout).

Each build uses up to four parallel compile jobs by default. Set `CMAKE_BUILD_PARALLEL_LEVEL=2` if you need to reduce compiler memory use. **F4** cycles through the upscaling options with Vulkan, **F7** switches aspect ratios, and **F9** switches the upper-screen layout.

## Optional HD textures

The graphical Windows and Linux builders offer the [1080p and 4K texture packs by Henriko Magnifico](https://www.henrikomagnifico.com/super-mario-3d-land-hd). **Install HD textures (1080p, 107 MB)** starts checked; **Install 4K textures (184 MB)** starts unchecked. Both can be installed. The downloads run after compilation, show their own percentage, and verify the ZIPs before installation. The highest successfully installed selection is enabled at the end of the build. If a download fails, the builder reports which pack failed in its log without blocking the game build. You can then install it manually without rebuilding.

For an existing command-line build, run `python tools/hd_pack.py dist` on Windows or `python3 tools/hd_pack.py dist/linux-x64` on Linux. Add `--4k` to install that edition instead. Use the folder containing the game executable if you built to a custom location. With Vulkan, choose **None**, **1080p**, or **4K** from **HD** on Windows or cycle through the available options with **Ctrl+F10** on Linux. A missing or incomplete pack cannot be selected.

### Manual texture installation

1. Close the game. Download the v1.2.0b [1080p ZIP](https://drive.google.com/file/d/1J0aEd7K6DUkNHcYsU42SBmxpNcZpC2Wd/view) or [4K ZIP](https://drive.google.com/file/d/1EG2kf2-_i1k5VCN9foHnS6DkQtdwz80Y/view), then extract it.
2. In the extracted pack, find `0004000000054000`. Copy its 297 `tex1_…_mip0.png` files directly into one of the folders below, **next to the game executable**, not next to the builder. Create the folders if needed. Do not copy the ZIP, the `0004000000054000` folder itself, or any ReShade files.

   - **1080p:** `userdata/hd-textures/sm3dl-1080p-1.2.0b/`
   - **4K:** `userdata/hd-textures/sm3dl-4k-1.2.0b/`

3. Start the game and select the pack in **HD** on Windows or with **Ctrl+F10** on Linux. No rebuild is needed.

If Python is available, you can also install the downloaded ZIP from the project's `source` directory with `python tools/hd_pack.py "GameFolder" --archive "Textures.zip" --4k` (use `python3` on Linux and omit `--4k` for 1080p). This verifies the ZIP and extracts just the texture PNGs.
