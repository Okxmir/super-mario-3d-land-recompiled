using Microsoft.Win32;
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;

internal sealed partial class Launcher
{
    private static readonly Regex CompileCount = new Regex(@"^\s*\[(\d+)/(\d+)\]");
    private static readonly Regex DownloadPercent = new Regex(@"^HD download:.*?\s-\s(\d+)%$");
    private DateTime etaStarted;
    private double etaFirst;
    private string hdProgress;

    private void ResolveGame()
    {
        string linked = Pref("linked", "");
        exe = requiredVersion != null && currentBuildVerified && LauncherCore.ValidGame(core.LocalExe) ? core.LocalExe :
            LauncherCore.ValidGame(linked) ? linked :
            (LauncherCore.ValidGame(core.LocalExe) ? core.LocalExe : null);
    }

    private void SettingsChanged()
    {
        if (updating) return;
        prefs["fps_target"] = Value("FpsBox");
        prefs["resolution"] = Value("ScaleBox");
        prefs["aspect_ratio"] = Value("AspectBox");
        prefs["single_screen"] = Value("LayoutBox");
        prefs["hd_quality"] = Value("TextureBox");
        prefs["language"] = Value("LanguageBox");
        prefs["fullscreen"] = Checked("FullscreenCheck") ? "1" : "0";
        prefs["vsync"] = Checked("VsyncCheck") ? "1" : "0";
        prefs["pack1080"] = Checked("Pack1080Check") ? "1" : "0";
        prefs["pack4k"] = Checked("Pack4kCheck") ? "1" : "0";
        SavePreferences();
        RefreshState();
    }

    private void SavePreferences()
    {
        if (demo) return;
        prefs.Remove("ui");
        prefs["launcher_version"] = LauncherUpdater.Current.ToString();
        prefs["rom"] = rom;
        try { LauncherCore.WriteSettings(core.Preferences, prefs); }
        catch (IOException error) { Error(error.Message); }
        catch (UnauthorizedAccessException error) { Error(error.Message); }
    }

    private void PickRom()
    {
        var dialog = new OpenFileDialog {
            Title = "Select a decrypted European ROM",
            Filter = "3DS ROM (*.3ds; *.cci; *.cxi)|*.3ds;*.cci;*.cxi",
            CheckFileExists = true,
        };
        if (dialog.ShowDialog(window) != true) return;
        SetRom(dialog.FileName);
    }

    private static bool ValidRom(string path)
    {
        if (!File.Exists(path)) return false;
        string extension = Path.GetExtension(path).ToLowerInvariant();
        return extension == ".3ds" || extension == ".cci" || extension == ".cxi";
    }

    private static string DroppedRom(IDataObject data)
    {
        if (!data.GetDataPresent(DataFormats.FileDrop)) return null;
        var files = data.GetData(DataFormats.FileDrop) as string[];
        return files != null && files.Length == 1 && ValidRom(files[0]) ? files[0] : null;
    }

    private void SetRom(string path)
    {
        if (!ValidRom(path)) {
            Error("Choose a .3ds, .cci or .cxi file.");
            return;
        }
        rom = path;
        SavePreferences();
        RefreshState();
    }

    private void PickGame()
    {
        if (LauncherRequired || RebuildRequired) return;
        var dialog = new OpenFileDialog {
            Title = "Select the previously built game",
            Filter = "Super Mario 3D Land|" + LauncherCore.GameName,
            CheckFileExists = true,
        };
        if (dialog.ShowDialog(window) != true) return;
        if (!LauncherCore.ValidGame(dialog.FileName)) {
            Error("Select SuperMario3DLandRecompiled.exe from the complete build folder, including its companion files.");
            return;
        }
        prefs["linked"] = dialog.FileName;
        prefs.Remove("save_profile_link");
        ResolveGame();
        SavePreferences();
        PopulateOptions();
        ShowPage(Home);
    }

    private void Launch()
    {
        if (PlayBlocked || busy || running != null) return;
        if (requiredVersion != null && !core.BuiltWith(LauncherUpdater.Current)) {
            currentBuildVerified = false;
            ShowPage(Home);
            return;
        }
        ResolveGame();
        if (exe == null) { ShowPage(Rom); return; }
        var settings = new System.Collections.Generic.Dictionary<string, string> {
            { "fps_target", Value("FpsBox") },
            { "resolution", Value("ScaleBox") },
            { "aspect_ratio", Value("AspectBox") },
            { "single_screen", Value("LayoutBox") },
            { "picture_in_picture", "0" }, { "smart_layout", "0" }, { "swap_screens", "0" },
            { "gpu_renderer", "1" },
            { "hd_quality", Value("TextureBox") },
            { "fullscreen", Checked("FullscreenCheck") ? "1" : "0" },
            { "vsync", Checked("VsyncCheck") ? "1" : "0" },
        };
        int language = Array.IndexOf(LauncherCore.Languages, Value("LanguageBox"));
        settings["language"] = LauncherCore.LanguageIds[Math.Max(0, language)].ToString();
        ApplyControlPreferences(settings);
        running = new Process { StartInfo = core.GameStart(exe, settings, Pref("save_profile_link", "")), EnableRaisingEvents = true };
        var game = running;
        game.Exited += (s, e) => window.Dispatcher.BeginInvoke(new Action(() => {
            if (running != game) return;
            int code = game.ExitCode;
            running = null;
            game.Dispose();
            RefreshState();
            if (code != 0) Error("The game closed with exit code " + code + ".");
        }));
        try {
            if (!game.Start()) throw new InvalidOperationException("The game did not start.");
        } catch {
            running = null;
            game.Dispose();
            RefreshState();
            throw;
        }
        RefreshState();
    }

    internal void VerifyPlay()
    {
        if (exe == null) throw new InvalidOperationException("The QA build was not recognized.");
        if (page != Home || !Find<FrameworkElement>("ReadyPane").IsVisible)
            throw new InvalidOperationException("The installed game did not show the Play page.");
        Press("SettingsButton");
        if (page != Graphics) throw new InvalidOperationException("The title-bar settings gear did not open.");
        Press("SettingsBack");
        VerifyReadyLayout();
        Press("PlaySettingsButton");
        if (page != Graphics) throw new InvalidOperationException("The Settings button next to Play did not open.");
        var fps = Find<ComboBox>("FpsBox");
        fps.SelectedIndex = 1;
        if (Pref("fps_target", "") != "60") throw new InvalidOperationException("60 FPS was not saved.");
        fps.SelectedIndex = 0;
        if (Pref("fps_target", "") != "30") throw new InvalidOperationException("30 FPS was not saved.");
        Press("ControlsNav");
        if (page != Controls) throw new InvalidOperationException("The controls page did not open.");
        VerifyControlsEditor();
        Press("SettingsBack");
        if (page != Home) throw new InvalidOperationException("Closing settings did not restore the home page.");
        Press("PlayButton");
        var started = running;
        if (started == null) throw new InvalidOperationException("Play did not start the game.");
        try {
            var wait = Stopwatch.StartNew();
            while (wait.Elapsed.TotalSeconds < 20 && !started.HasExited) {
                started.Refresh();
                if (started.MainWindowHandle != IntPtr.Zero) break;
                System.Threading.Thread.Sleep(100);
            }
            if (started.HasExited || started.MainWindowHandle == IntPtr.Zero)
                throw new InvalidOperationException("The game did not display a window.");
            var cfg = LauncherCore.ReadSettings(Path.Combine(core.Profile(exe), "settings.ini"));
            if (LauncherCore.Get(cfg, "fps_target", "") != "30" || LauncherCore.Get(cfg, "resolution", "") != "1" ||
                LauncherCore.Get(cfg, "key_b", "") != "G" || LauncherCore.Get(cfg, "pad_b", "") != "righttrigger")
                throw new InvalidOperationException("The launcher did not write the expected game settings.");
        } finally {
            running = null;
            if (!started.HasExited && (!started.CloseMainWindow() || !started.WaitForExit(4500))) {
                started.Kill();
                started.WaitForExit(3000);
            }
            started.Dispose();
        }
    }

    private void VerifyReadyLayout()
    {
        var saves = Find<Button>("SavesButton");
        var card = Find<Border>("InstallationCard");
        var play = Find<Button>("PlayButton");
        var settings = Find<Button>("PlaySettingsButton");
        var width = window.Width;
        foreach (var testWidth in new[] { width, window.MinWidth }) {
            window.Width = testWidth;
            window.UpdateLayout();
            var origin = new Point(0, 0);
            var savesPos = saves.TranslatePoint(origin, window);
            var cardPos = card.TranslatePoint(origin, window);
            var playPos = play.TranslatePoint(origin, window);
            var settingsPos = settings.TranslatePoint(origin, window);
            if (Math.Abs(savesPos.Y - cardPos.Y) > 1 || Math.Abs(saves.ActualHeight - card.ActualHeight) > 1 ||
                cardPos.X <= savesPos.X || Math.Abs(playPos.Y - settingsPos.Y) > 1 ||
                settingsPos.X < playPos.X + play.ActualWidth || settingsPos.X + settings.ActualWidth > savesPos.X + saves.ActualWidth + 1)
                throw new InvalidOperationException("The Ready layout cards or buttons were not aligned.");
        }
        window.Width = width;
        window.UpdateLayout();
    }

    private void Press(string name) { Find<Button>(name).RaiseEvent(new RoutedEventArgs(Button.ClickEvent)); }

    internal void VerifyWizard(string file)
    {
        if (exe != null || page != Home) throw new InvalidOperationException("Expected an empty launcher profile.");
        Press("SetupButton");
        if (page != Rom || Find<Button>("WizardNext").IsEnabled) throw new InvalidOperationException("Expected a ROM before continuing.");
        Press("WizardNext");
        if (page != Rom) throw new InvalidOperationException("The wizard let an empty ROM continue.");
        var dropped = new DataObject(DataFormats.FileDrop, new[] { file });
        string selected = DroppedRom(dropped);
        if (selected != file) throw new InvalidOperationException("The valid file could not be dropped.");
        SetRom(selected);
        Press("WizardNext");
        if (page != OptionsScreen) throw new InvalidOperationException("The options page did not open.");
        Find<ComboBox>("LanguageBox").SelectedIndex = 1;
        Find<CheckBox>("Pack4kCheck").IsChecked = true;
        SettingsChanged();
        Press("WizardNext");
        if (page != Compile || !Find<Button>("BuildButton").IsEnabled ||
            !Find<TextBlock>("BuildSelection").Text.Contains("French") ||
            !Find<TextBlock>("BuildSelection").Text.Contains("4K"))
            throw new InvalidOperationException("The build review did not reflect the choices.");
        Press("CompileLogButton");
        if (page != Journal) throw new InvalidOperationException("The journal did not open.");
        Press("SettingsBack");
        Press("WizardBack");
        if (page != OptionsScreen || Value("LanguageBox") != "fr" || !Checked("Pack4kCheck"))
            throw new InvalidOperationException("Going back lost the build options.");
    }

    internal void VerifyUpdateGate()
    {
        string linked = exe;
        if (!LauncherCore.ValidGame(linked)) throw new InvalidOperationException("Missing linked-game fixture.");
        requiredVersion = new Version(LauncherUpdater.Current.Major, LauncherUpdater.Current.Minor, LauncherUpdater.Current.Build + 1, 0);
        core.RequireVersion(requiredVersion);
        ShowPage(Home);
        Launch();
        if (!Find<FrameworkElement>("UpdateShell").IsVisible || running != null || Find<Button>("PlayButton").IsEnabled)
            throw new InvalidOperationException("The newer launcher requirement did not block Play.");
        requiredVersion = LauncherUpdater.Current;
        LauncherCore.WriteSettings(core.UpdateState, new System.Collections.Generic.Dictionary<string, string> {
            { "launcher_version", requiredVersion.ToString() }
        });
        ShowPage(Home);
        Launch();
        if (!Find<FrameworkElement>("RebuildPane").IsVisible || running != null || Find<Button>("PlayButton").IsEnabled)
            throw new InvalidOperationException("The rebuild requirement did not block the old linked game.");
        Press("RebuildButton");
        if (page != Rom) throw new InvalidOperationException("Rebuild did not open the ROM wizard.");
        Directory.CreateDirectory(core.Game);
        foreach (string file in new[] { LauncherCore.GameName, "SDL3.dll", "SM3DL-EUR.cxi", "mii.romfs", "shared-font.bcfnt" })
            File.WriteAllText(Path.Combine(core.Game, file), "QA fixture");
        if (core.BuiltWith(LauncherUpdater.Current)) throw new InvalidOperationException("An unrecorded build passed validation.");
        core.RecordBuild();
        currentBuildVerified = core.BuiltWith(LauncherUpdater.Current);
        if (!currentBuildVerified || RebuildRequired) throw new InvalidOperationException("A successful build receipt did not unlock the launcher.");
        ResolveGame();
        var start = core.GameStart(exe, new System.Collections.Generic.Dictionary<string, string>(), linked);
        if (exe != core.LocalExe || start.EnvironmentVariables["SM3DL_SAVE_DIR"] != core.Profile(linked) ||
            start.EnvironmentVariables["SM3DL_DATA_DIR"] != core.Profile(core.LocalExe))
            throw new InvalidOperationException("The rebuilt game would not retain the linked game's saves.");
        File.AppendAllText(core.LocalExe, "changed");
        Launch();
        if (!RebuildRequired || running != null) throw new InvalidOperationException("Replacing the rebuilt EXE bypassed verification.");
    }

    private async Task Build()
    {
        if (page != Compile || busy || checkingUpdate || LauncherRequired || running != null || !ValidRom(rom)) return;
        string selectedRom = rom;
        string language = Value("LanguageBox");
        bool use1080 = Checked("Pack1080Check"), use4K = Checked("Pack4kCheck");
        progress = 1;
        hdProgress = "";
        etaStarted = DateTime.MinValue;
        state = "preparing";
        busy = true;
        timer.Restart();
        Find<TextBox>("JournalText").Clear();
        ShowPage(Compile);
        var updater = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1) };
        updater.Tick += (s, e) => RefreshBuildStatus();
        updater.Start();
        try {
            string linked = Pref("linked", "");
            if (!String.IsNullOrEmpty(linked) && !String.Equals(linked, core.LocalExe, StringComparison.OrdinalIgnoreCase)) {
                prefs["save_profile_link"] = linked;
                LauncherCore.WriteSettings(core.Preferences, prefs);
            }
            bool warn = await Task.Run(() => core.Build(selectedRom, language, use1080, use4K,
                line => window.Dispatcher.BeginInvoke(DispatcherPriority.Normal, new Action(() => ReadBuildLine(line)))));
            core.RecordBuild();
            currentBuildVerified = true;
            prefs.Remove("linked");
            ResolveGame();
            string profile = exe == null ? null : core.Profile(exe);
            prefs["hd_quality"] = use4K && LauncherCore.HasPack(profile, 2) ? "2" :
                (use1080 && LauncherCore.HasPack(profile, 1) ? "1" : "0");
            SavePreferences();
            PopulateOptions();
            progress = 100;
            state = warn ? "warning" : "ready";
        } catch (Exception error) {
            ReadBuildLine(error.Message);
            state = "failed";
        } finally {
            busy = false;
            timer.Stop();
            updater.Stop();
            ShowPage(state == "failed" ? Compile : Home);
        }
    }

    private void ReadBuildLine(string line)
    {
        var journal = Find<TextBox>("JournalText");
        if (journal.Text.Length > 45000) journal.Text = journal.Text.Substring(journal.Text.Length - 24000);
        journal.AppendText(line + Environment.NewLine);
        if (page == Journal) journal.ScrollToEnd();
        if (!busy) return;
        if (line.StartsWith("Build stage: ", StringComparison.Ordinal)) {
            switch (line.Substring(13).Trim()) {
                case "Preparing dependencies": state = "preparing"; progress = Math.Max(progress, 3); break;
                case "Extracting the ROM": state = "extracting"; progress = Math.Max(progress, 10); break;
                case "Recompiling ARM code": state = "translating"; progress = Math.Max(progress, 16); break;
                case "Preparing game resources": state = "resources"; progress = Math.Max(progress, 22); break;
                case "Compiling the game": state = "compiling"; progress = Math.Max(progress, 28); break;
                case "Running tests": state = "testing"; progress = Math.Max(progress, 95); break;
                case "Writing game files": state = "packaging"; progress = Math.Max(progress, 98); break;
                case "Installing HD textures": state = "hd"; progress = Math.Max(progress, 99); break;
            }
        }
        if (state == "compiling") {
            var match = CompileCount.Match(line);
            double done, count;
            if (match.Success && double.TryParse(match.Groups[1].Value, out done) &&
                double.TryParse(match.Groups[2].Value, out count) && count > 0) {
                progress = Math.Max(progress, 28 + 65 * Math.Min(1, done / count));
                if (etaStarted == DateTime.MinValue) { etaStarted = DateTime.UtcNow; etaFirst = progress; }
            }
        }
        if (state == "hd") {
            var match = DownloadPercent.Match(line);
            if (match.Success) hdProgress = "  ·  " + line.Substring("HD download: ".Length);
        }
        RefreshBuildStatus();
    }

    private void RefreshBuildStatus()
    {
        string detail;
        switch (state) {
            case "preparing": detail = "Preparing dependencies"; break;
            case "extracting": detail = "Validating and extracting the ROM"; break;
            case "translating": detail = "Recompiling ARM code"; break;
            case "resources": detail = "Preparing game resources"; break;
            case "compiling": detail = "Compiling the game"; break;
            case "testing": detail = "Running tests"; break;
            case "packaging": detail = "Writing game files"; break;
            case "hd": detail = "Installing HD textures" + hdProgress; break;
            case "ready": detail = "Finished. Click Play to start."; break;
            case "warning": detail = "Game ready, but an HD pack was not installed. See the log."; break;
            case "failed": detail = "Build failed. See the activity log."; break;
            default: detail = "The first build downloads its tools automatically."; break;
        }
        Find<ProgressBar>("Progress").Value = progress;
        if (busy) {
            detail = LauncherCore.Number(Math.Floor(progress)) + " %  ·  " + detail +
                "  ·  " + timer.Elapsed.ToString(@"hh\:mm\:ss");
            double seconds = (DateTime.UtcNow - etaStarted).TotalSeconds;
            if (state == "compiling" && seconds > 12 && progress - etaFirst > 3 && etaStarted != DateTime.MinValue) {
                double estimate = (93 - progress) * seconds / (progress - etaFirst);
                if (estimate > 1 && estimate < 86400)
                    detail += "  ·  compile time left ≈ " +
                        TimeSpan.FromSeconds(estimate).ToString(@"hh\:mm\:ss");
            }
        }
        Find<TextBlock>("BuildStatus").Text = detail;
    }

    private void RefreshState()
    {
        bool playing = running != null;
        bool selected = ValidRom(rom) || previewRom;
        bool ready = exe != null || previewReady;
        Visible("WelcomePane", !ready && !RebuildRequired);
        Visible("ReadyPane", ready && !RebuildRequired);
        Caption("PlayButton", playing ? "Running…" : "▶  Play");
        Find<Button>("PlayButton").IsEnabled = ready && !busy && !playing && !PlayBlocked;
        Find<Button>("NewBuildButton").IsEnabled = !busy && !playing;
        Find<Button>("SavesButton").IsEnabled = exe != null || previewReady;
        Find<Button>("InstallFolderButton").IsEnabled = exe != null || previewReady;
        Find<Button>("SettingsButton").IsEnabled = !busy;
        Find<Button>("BuildButton").IsEnabled = selected && !busy && !playing && !checkingUpdate && !LauncherRequired;
        Find<Button>("WizardNext").IsEnabled = selected && !busy && !playing;
        Find<Button>("WizardBack").IsEnabled = !busy;
        foreach (string name in new[] { "BrowseButton", "LinkGameButton" }) Find<Button>(name).IsEnabled = !busy && !playing;
        foreach (string name in new[] { "Pack1080Check", "Pack4kCheck" }) Find<CheckBox>(name).IsEnabled = !busy;
        Find<ComboBox>("LanguageBox").IsEnabled = !busy;
        Text("StatusTitle", playing ? "Game is running" : "Ready to play");
        if (state == "warning")
            Text("StatusDetail", "Game ready. An HD pack could not be installed.");
        else Text("StatusDetail", "Native PC port · Windows x64");
        Text("InstallTitle", "Super Mario 3D Land");
        bool linked = exe != null && !String.Equals(exe, core.LocalExe, StringComparison.OrdinalIgnoreCase);
        Text("InstallDetail", linked ? "Linked game · separate saves" : "Local installation · Windows x64");
        string file = previewRom ? "Super Mario 3D Land (Europe).3ds" : Path.GetFileName(rom);
        if (selected) Find<TextBlock>("RomPathText").Text = file;
        else Text("RomPathText", "No ROM selected");
        Find<TextBlock>("RomPathText").ToolTip = ValidRom(rom) ? rom : null;
        string packs = Checked("Pack1080Check") ? (Checked("Pack4kCheck") ? "1080p + 4K" : "1080p") :
            (Checked("Pack4kCheck") ? "4K" : "No HD pack");
        var language = (ComboBoxItem)Find<ComboBox>("LanguageBox").SelectedItem;
        Find<TextBlock>("BuildSelection").Text = selected && language != null ? file + "  ·  " + language.Content + "  ·  " + packs : "";
        if (page == Rom) Text("WizardNote", selected ? "The ROM is checked before compilation." : "Choose a file to continue.");
        else if (page == OptionsScreen) Text("WizardNote", "HD textures are optional.");
        else Text("WizardNote", "The game is built on your PC.");
        RefreshBuildStatus();
        RefreshUpdateControls();
    }
}
