using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media.Imaging;

internal sealed partial class Launcher
{
    private const int Home = 0, Rom = 1, OptionsScreen = 2, Compile = 3, Graphics = 4, Controls = 5, Journal = 6;
    private static readonly string[] Pages = { "Home", "Rom", "Options", "Compile", "Graphics", "Controls", "Log" };
    private readonly Window window;
    private readonly LauncherCore core;
    private readonly bool demo;
    private readonly Dictionary<string, string> prefs;
    private readonly Stopwatch timer = new Stopwatch();
    private string state = "idle", rom, exe;
    private double progress;
    private int page, settingsReturn;
    private bool updating, busy, previewReady, previewRom;
    private Process running;

    internal Launcher(Window window, LauncherCore core, bool demo)
    {
        this.window = window;
        this.core = core;
        this.demo = demo;
        prefs = demo ? new Dictionary<string, string>() : LauncherCore.ReadSettings(core.Preferences);
        rom = Pref("rom", "");
        using (Stream icon = Assembly.GetExecutingAssembly().GetManifestResourceStream("LauncherIcon.png")) {
            BitmapFrame bitmap = BitmapFrame.Create(icon, BitmapCreateOptions.None, BitmapCacheOption.OnLoad);
            bitmap.Freeze();
            window.Icon = bitmap;
            Find<Image>("TitleIcon").Source = bitmap;
            Find<Image>("WelcomeIcon").Source = bitmap;
            Find<Image>("UpdateIcon").Source = bitmap;
            Find<Image>("RebuildIcon").Source = bitmap;
        }
        window.SourceInitialized += (s, e) => {
            var chrome = new System.Windows.Shell.WindowChrome { CaptionHeight = 0, ResizeBorderThickness = new Thickness(5),
                CornerRadius = new CornerRadius(13), GlassFrameThickness = new Thickness(0), UseAeroCaptionButtons = false };
            System.Windows.Shell.WindowChrome.SetWindowChrome(window, chrome);
        };
        Find<Border>("TitleBar").MouseLeftButtonDown += (s, e) => {
            if (e.ChangedButton == MouseButton.Left && window.WindowState == WindowState.Normal) window.DragMove();
        };
        Click("MinButton", () => window.WindowState = WindowState.Minimized);
        Click("CloseButton", window.Close);
        Click("SetupButton", () => ShowPage(Rom));
        Click("NewBuildButton", () => ShowPage(Rom));
        Click("WizardBack", WizardBack);
        Click("WizardNext", WizardNext);
        Click("SettingsButton", () => OpenSettings(Graphics));
        Click("PlaySettingsButton", () => OpenSettings(Graphics));
        Click("SettingsBack", () => ShowPage(settingsReturn));
        Click("GraphicsNav", () => OpenSettings(Graphics));
        Click("ControlsNav", () => OpenSettings(Controls));
        Click("LogNav", () => OpenSettings(Journal));
        Click("CompileLogButton", () => OpenSettings(Journal));
        Click("PlayButton", Launch);
        Click("BrowseButton", PickRom);
        Click("LinkGameButton", PickGame);
        Find<Button>("BuildButton").Click += async (s, e) => await Build();
        Click("SavesButton", () => OpenFolder(Path.Combine(core.SaveProfile(exe, Pref("save_profile_link", "")), "games")));
        Click("InstallFolderButton", () => OpenFolder(Path.GetDirectoryName(exe)));
        Click("OpenFolderButton", () => OpenFolder(core.Root));
        Click("CopyLogButton", () => Clipboard.SetText(Find<TextBox>("JournalText").Text));
        window.DragOver += (s, e) => {
            e.Effects = page == Rom && !busy && !String.IsNullOrEmpty(DroppedRom(e.Data)) ? DragDropEffects.Copy : DragDropEffects.None;
            e.Handled = true;
        };
        window.Drop += (s, e) => {
            string path = DroppedRom(e.Data);
            if (page == Rom && !busy && path != null) SetRom(path);
            e.Handled = true;
        };
        window.PreviewKeyDown += (s, e) => {
            if (e.Key != Key.Escape || e.Handled ||
                FocusedComboDropDown()) return;
            if (page >= Graphics) { ShowPage(settingsReturn); e.Handled = true; }
            else if (IsWizard && !busy) { WizardBack(); e.Handled = true; }
        };
        window.Closing += (s, e) => {
            if (!busy) { if (!demo) SavePreferences(); }
            else {
                e.Cancel = true;
                MessageBox.Show(window, "Build in progress.", window.Title, MessageBoxButton.OK, MessageBoxImage.Information);
            }
        };
        foreach (string name in new[] { "FpsBox", "ScaleBox", "AspectBox", "LayoutBox", "TextureBox", "LanguageBox" })
            Find<ComboBox>(name).SelectionChanged += (s, e) => SettingsChanged();
        foreach (string name in new[] { "FullscreenCheck", "VsyncCheck", "Pack1080Check", "Pack4kCheck" })
            Find<CheckBox>(name).Click += (s, e) => SettingsChanged();
        if (File.Exists(core.Log) && !demo) {
            using (var log = new FileStream(core.Log, FileMode.Open, FileAccess.Read, FileShare.ReadWrite)) {
                log.Seek(Math.Max(0, log.Length - 30000), SeekOrigin.Begin);
                using (var reader = new StreamReader(log, Encoding.UTF8)) Find<TextBox>("JournalText").Text = reader.ReadToEnd();
            }
        }
        InitializeUpdateState();
        ResolveGame();
        InitializeControls();
        InitializeLabels();
    }

    private TElement Find<TElement>(string name) where TElement : class { return (TElement)window.FindName(name); }
    private void Text(string name, string value) { Find<TextBlock>(name).Text = value; }
    private void Caption(string name, string value) { Find<ContentControl>(name).Content = value; }
    private bool Checked(string name) { return Find<CheckBox>(name).IsChecked == true; }
    private void SetChecked(string name, string value) { Find<CheckBox>(name).IsChecked = value == "1"; }
    private string Pref(string key, string fallback) { return LauncherCore.Get(prefs, key, fallback); }
    private bool IsWizard { get { return page >= Rom && page <= Compile; } }

    private void Click(string name, Action action)
    {
        Find<Button>(name).Click += (s, e) => {
            try { action(); }
            catch (Exception error) { Error(error.Message); }
        };
    }

    private void Error(string message) { MessageBox.Show(window, message, window.Title, MessageBoxButton.OK, MessageBoxImage.Warning); }
    private void Visible(string name, bool visible) { Find<FrameworkElement>(name).Visibility = visible ? Visibility.Visible : Visibility.Collapsed; }
    private void OpenFolder(string path) {
        Directory.CreateDirectory(path);
        Process.Start("explorer.exe", "\"" + path + "\"");
    }

    private bool FocusedComboDropDown()
    {
        var combo = Keyboard.FocusedElement as ComboBox;
        return combo != null && combo.IsDropDownOpen;
    }

    private void ShowPage(int index)
    {
        if (page == Controls && index != Controls) CancelCapture(null);
        page = index;
        for (int i = 0; i < Pages.Length; i++) Visible(Pages[i] + "Page", i == page);
        Visible("WizardShell", IsWizard);
        Visible("Steps", IsWizard);
        Visible("SettingsShell", page >= Graphics);
        Find<Border>("RomStep").Tag = page == Rom ? "active" : null;
        Find<Border>("OptionsStep").Tag = page == OptionsScreen ? "active" : null;
        Find<Border>("CompileStep").Tag = page == Compile ? "active" : null;
        foreach (int i in new[] { Graphics, Controls, Journal }) {
            var nav = Find<Button>(Pages[i] + "Nav");
            nav.Opacity = page == i ? 1 : .66;
            nav.IsEnabled = !busy || i == Journal;
        }
        Visible("BuildButton", page == Compile);
        Visible("WizardNext", page != Compile);
        RefreshState();
        if (page == Controls) OpenControls();
    }

    private void OpenSettings(int index)
    {
        if (busy && index != Journal) return;
        if (page < Graphics) settingsReturn = page;
        ShowPage(index);
    }

    private void WizardBack()
    {
        if (busy || !IsWizard) return;
        ShowPage(page - 1);
    }

    private void WizardNext()
    {
        if (!busy && (page == Rom || page == OptionsScreen) && ValidRom(rom)) ShowPage(page + 1);
    }

    private void InitializeLabels()
    {
        Find<Button>("SettingsButton").ToolTip = "Settings";
        Find<Button>("CloseButton").ToolTip = "Close";
        Find<Button>("MinButton").ToolTip = "Minimize";
        Text("WelcomeTitle", "Build your game");
        Text("WelcomeDescription", "Turn your own European copy of Super Mario 3D Land into a PC game.");
        Caption("SetupButton", "Set up the game");
        Caption("LinkGameButton", "I already built the game");
        Text("WelcomeNote", "Your ROM and saves stay on this PC.");
        Caption("SavesButton", "Save files  ›");
        Caption("NewBuildButton", "+  New build");
        Caption("InstallFolderButton", "Open game folder  ↗");
        Text("InstallationLabel", "INSTALLATION");
        Text("RomStepLabel", "1  Game file");
        Text("OptionsStepLabel", "2  Options");
        Text("CompileStepLabel", "3  Build");
        Text("RomTitle", "Your game file");
        Text("RomLabel", "Select your decrypted European ROM. The file stays on this PC.");
        Text("RomHelp", "Drop a file here or browse your folders.");
        Caption("BrowseButton", "Browse…");
        Text("OptionsTitle", "Installation options");
        Text("OptionsIntro", "Choose the game language and which textures to download.");
        Text("GameLanguageLabel", "Game language");
        Text("PacksTitle", "HD textures");
        Caption("Pack1080Check", "Install the 1080p HD pack");
        Caption("Pack4kCheck", "Install the 4K HD pack");
        Text("PackCredit", "Henriko Magnifico · download from GitHub");
        Text("CompileTitle", "Build the game");
        Text("CompileIntro", "The first build prepares its tools automatically. Keep this window open.");
        Text("BuildSummary", "Installation summary");
        Caption("CompileLogButton", "View build log");
        Caption("WizardBack", "Back");
        Caption("WizardNext", "Next");
        Caption("BuildButton", "Build");
        Caption("SettingsBack", "Done");
        Caption("GraphicsNav", "Graphics");
        Caption("ControlsNav", "Controls");
        Caption("LogNav", "Log");
        Text("GraphicsTitle", "Graphics settings");
        Text("GraphicsNote", "Settings apply on the next launch. Only installed HD packs are available.");
        Text("FpsLabel", "Frame rate");
        Text("AspectLabel", "Aspect ratio");
        Text("DisplayLabel", "Screen layout");
        Text("TexturesLabel", "HD textures");
        Caption("FullscreenCheck", "Fullscreen");
        Text("LogTitle", "Build log");
        Caption("OpenFolderButton", "Launcher folder");
        Caption("CopyLogButton", "Copy log");
        var journal = Find<TextBox>("JournalText");
        if (journal.Text == "")
            journal.Text = "Build output will appear here.";
        PopulateOptions();
        ShowPage(page);
    }

    private void PopulateOptions()
    {
        updating = true;
        try {
            Options("FpsBox", Pref("fps_target", "60"), new[] { "30", "60" }, new[] { "30 FPS", "60 FPS" });
            Options("ScaleBox", Pref("resolution", "2"), new[] { "1", "2", "4" }, new[] { "1×", "2×", "4×" });
            Options("AspectBox", Pref("aspect_ratio", "1"), new[] { "0", "1", "2" }, new[] { "Original · 5:3", "16:9", "21:9 · experimental" });
            Options("LayoutBox", Pref("single_screen", "0"), new[] { "0", "1" }, new[] { "Stacked screens", "Widescreen" });
            Options("LanguageBox", Pref("language", "en"), LauncherCore.Languages, new[] { "English", "French", "German", "Italian", "Spanish", "Dutch", "Portuguese", "Russian" });
            var keys = new List<string> { "0" };
            var labels = new List<string> { "None" };
            string profile = exe == null ? null : core.Profile(exe);
            if (LauncherCore.HasPack(profile, 1)) { keys.Add("1"); labels.Add("1080p"); }
            if (LauncherCore.HasPack(profile, 2)) { keys.Add("2"); labels.Add("4K"); }
            Options("TextureBox", Pref("hd_quality", "0"), keys.ToArray(), labels.ToArray());
            Find<ComboBox>("TextureBox").IsEnabled = keys.Count > 1;
            SetChecked("FullscreenCheck", Pref("fullscreen", "0"));
            SetChecked("VsyncCheck", Pref("vsync", "1"));
            SetChecked("Pack1080Check", Pref("pack1080", "1"));
            SetChecked("Pack4kCheck", Pref("pack4k", "0"));
        } finally { updating = false; }
    }

    private void Options(string name, string selected, string[] values, string[] labels)
    {
        var box = Find<ComboBox>(name);
        box.Items.Clear();
        for (int i = 0; i < values.Length; i++) box.Items.Add(new ComboBoxItem { Tag = values[i], Content = labels[i] });
        box.SelectedIndex = Math.Max(0, Array.IndexOf(values, selected));
    }

    private string Value(string name) { return (string)((ComboBoxItem)Find<ComboBox>(name).SelectedItem).Tag; }

    internal void PreviewSetup(string name)
    {
        page = Math.Max(0, Array.IndexOf(Pages, name));
        previewReady = name == "Ready";
        if (name == "Rebuild") requiredVersion = LauncherUpdater.Current;
        if (name == "Update") requiredVersion = new Version(LauncherUpdater.Current.Major, LauncherUpdater.Current.Minor, LauncherUpdater.Current.Build + 1, 0);
        previewRom = page == OptionsScreen || page == Compile;
        if (name == "Controller") { page = Controls; SwitchInputMode(true); }
        ShowPage(page);
    }
}
