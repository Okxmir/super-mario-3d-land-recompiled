using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows;
using System.Windows.Markup;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;

internal static class Program
{
    [STAThread]
    internal static int Main(string[] args)
    {
        bool preview = args.Length >= 2 && args[0] == "--preview";
        bool verifyBuild = args.Length == 3 && args[0] == "--verify-build";
        bool verifyGate = args.Length == 4 && args[0] == "--verify-rebuild";
        bool verifyLaunch = args.Length == 4 && (args[0] == "--verify-launch" || verifyGate);
        bool verifyWizard = args.Length == 4 && args[0] == "--verify-wizard";
        try {
            if (args.Length > 0 && args[0] == "--finish-update") { LauncherUpdater.Finish(args); return 0; }
            if (args.Length == 3 && args[0] == "--verify-release-feed") {
                var candidate = LauncherUpdater.ParseReleases(File.ReadAllText(args[1]));
                File.WriteAllText(args[2], candidate == null ? "none" : candidate.Version.ToString());
                return 0;
            }
            if (args.Length == 5 && args[0] == "--verify-rar-update") {
                try {
                    var candidate = LauncherUpdater.ParseReleases(File.ReadAllText(args[1]));
                    if (candidate == null || !candidate.IsArchive) throw new InvalidDataException("The RAR asset was not selected.");
                    Directory.CreateDirectory(args[3]);
                    string sha = LauncherUpdater.PrepareUpdate(candidate, Path.GetFullPath(args[2]), Path.GetFullPath(args[3]));
                    File.WriteAllText(args[4], sha);
                    return 0;
                } catch (Exception error) {
                    File.WriteAllText(args[4], error.Message);
                    return 1;
                }
            }
            string root = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "LauncherData");
            if (args.Length == 2 && args[0] == "--verify-sources") {
                new LauncherCore(args[1]).InstallSources();
                return 0;
            }
            if (verifyBuild) return new LauncherCore(args[1]).Build(args[2], "en", false, false, _ => { }) ? 1 : 0;
            var app = new Application { ShutdownMode = ShutdownMode.OnMainWindowClose };
            app.DispatcherUnhandledException += (s, e) => {
                e.Handled = true;
                if (preview) {
                    File.WriteAllText(args[1] + ".error.txt", e.Exception.ToString());
                    app.Shutdown(1);
                } else {
                    MessageBox.Show(e.Exception.Message, "3D Land Launcher", MessageBoxButton.OK, MessageBoxImage.Warning);
                }
            };
            Window window;
            using (Stream markup = Assembly.GetExecutingAssembly().GetManifestResourceStream("Launcher.xaml"))
                window = (Window)XamlReader.Load(markup);
            if (verifyWizard) root = Path.GetFullPath(args[1]);
            if (verifyLaunch) {
                root = Path.GetFullPath(args[1]);
                var settings = LauncherCore.ReadSettings(Path.Combine(root, "launcher.ini"));
                settings["linked"] = Path.GetFullPath(args[2]);
                settings["fps_target"] = "30";
                settings["resolution"] = "1";
                LauncherCore.WriteSettings(Path.Combine(root, "launcher.ini"), settings);
            }
            var launcher = new Launcher(window, new LauncherCore(root), preview);
            if (!preview && !verifyLaunch && !verifyWizard) launcher.StartUpdateChecks();
            if (verifyLaunch || verifyWizard) {
                window.ShowInTaskbar = false;
                window.Loaded += (s, e) => window.Dispatcher.BeginInvoke(DispatcherPriority.ApplicationIdle, new Action(() => {
                    try {
                        if (verifyGate) {
                            launcher.VerifyUpdateGate();
                            File.WriteAllText(args[3], "Required launcher and rebuild both blocked Play; receipt, tamper check, and linked save profile verified.");
                        } else if (verifyWizard) {
                            launcher.VerifyWizard(Path.GetFullPath(args[2]));
                            File.WriteAllText(args[3], "Home, ROM selection, options, compile summary and log navigation verified.");
                        } else {
                            launcher.VerifyPlay();
                            File.WriteAllText(args[3], "Game window opened after keyboard capture and SDL virtual controller checks. Both remaps reached the isolated game profile.");
                        }
                        app.Shutdown();
                    } catch (Exception error) {
                        File.WriteAllText(args[3], error.ToString());
                        app.Shutdown(1);
                    }
                }));
            }
            if (preview) {
                window.ShowInTaskbar = false;
                if (args.Length >= 3) launcher.PreviewSetup(args[2]);
                window.Loaded += (s, e) => window.Dispatcher.BeginInvoke(DispatcherPriority.ApplicationIdle, new Action(() => {
                    window.UpdateLayout();
                    var content = (FrameworkElement)window.Content;
                    var bitmap = new RenderTargetBitmap((int)Math.Ceiling(content.ActualWidth),
                        (int)Math.Ceiling(content.ActualHeight), 96, 96, PixelFormats.Pbgra32);
                    bitmap.Render(content);
                    var png = new PngBitmapEncoder();
                    png.Frames.Add(BitmapFrame.Create(bitmap));
                    using (var output = File.Create(args[1])) png.Save(output);
                    app.Shutdown();
                }));
            }
            return app.Run(window);
        } catch (Exception error) {
            if (verifyLaunch || verifyWizard) File.WriteAllText(args[3], error.ToString());
            else if (preview || verifyBuild || args.Length == 2 && args[0] == "--verify-sources")
                File.WriteAllText(args[1] + ".error.txt", error.ToString());
            else MessageBox.Show(error.Message, "3D Land Launcher", MessageBoxButton.OK, MessageBoxImage.Error);
            return 1;
        }
    }
}
