# Graphical launcher

The launcher is in English. You can independently build the game in English, French, German, Italian, Spanish, Dutch, Portuguese or Russian. It needs your own supported decrypted European ROM (`.3ds`, `.cci` or `.cxi`). No ROM or compiled game files are included.

- **Windows x64:** open the launcher EXE. The game build downloads the portable tools; installing Python or Visual Studio is not required.
- **Linux x86-64:** install the [Linux prerequisites](../BUILD.md#linux-x86-64), extract the whole release and run `bash SuperMario3DLandBuilder` in the extracted directory. The same command works from a Git checkout.
- Choose **Set up the game** to build locally, or **I already built the game** to associate a complete existing game folder. A linked installation's original files are not overwritten. The launcher uses its own save profile.
- **Settings → Controls** remaps the keyboard and controller independently. Click a control on the diagram or in the list. On Linux, live capture requires a shared SDL3 library; the manual controller menu does not. The controller's left stick remains the Circle Pad. The mouse is used for the touchscreen. Changes apply on the next launch, without rebuilding.
- Keep the `LauncherData` folder when moving or updating the launcher. The **Save files** button opens the profile this launcher uses.

## Create release assets

Build commands from the repository root:

```powershell
pwsh -File launcher/windows/build.ps1 -ReleaseAsset
```

```bash
python3 launcher/linux/package.py --revision YOUR_TESTED_GAME_COMMIT
```

The Windows packager uses the tested game commit pinned in `launcher/windows/LauncherCore.cs`. The Linux packager takes the tested game commit as an argument. The game snapshot is archived from Git, so uncommitted source edits are not included unintentionally.

Increment the relevant internal launcher version before publishing (`LauncherUpdater.VersionText` on Windows, `model.VERSION` on Linux). Upload the generated `Super-Mario-3D-Land-Windows-x64-vX.Y.Z.rar` and `Super-Mario-3D-Land-Linux-x64-vX.Y.Z.tar.gz` as assets of a public stable release. The new launchers also accept the older `SM3DL-Launcher-…` asset names. GitHub's SHA-256 digest is used to verify every update. A code push by itself does not trigger an update. Linux source checkouts do not self-update; use Git to update them.

The RAR-enabled Windows 1.1.5 build can update from just the RAR. Keep the exact generated asset name; the RAR5 archive must contain only `SM3DL-Launcher.exe` at its root. The publisher's build command uses Rar.exe to create it, but players do not need WinRAR installed to receive automatic updates. The Windows launcher includes the unmodified [UnRAR reader](https://www.rarlab.com/rar_add.htm) and its [notice](windows/assets/UnRAR-NOTICE.txt).

Players with the earlier Windows 1.1.5 build must extract the RAR-enabled 1.1.5 and replace their launcher executable once, keeping `LauncherData`: the launcher does not reinstall an equal version. For older launchers below 1.1.5, automatic migration is optional: use `-IncludeLegacyExe` and publish the additional `SM3DL-Launcher-v1.1.5.exe` next to the RAR. After the RAR-enabled build is installed, use only the RAR for future Windows releases, with a higher internal version each time.

The packaged launcher checks when idle. After it detects a newer version, **Play** remains unavailable until installation and a successful **Rebuild game**. The launcher reuses the ROM path if it is still available and keeps the existing save profile. The first version with auto-update must be installed manually by users of the older builders.
