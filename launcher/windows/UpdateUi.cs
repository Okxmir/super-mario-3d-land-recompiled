using System;
using System.IO;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;

internal sealed partial class Launcher
{
    private Version requiredVersion;
    private bool currentBuildVerified, checkingUpdate, downloadingUpdate, updateUnavailable;
    private string updateMessage = "";
    private DispatcherTimer scheduledUpdate;
    private bool LauncherRequired { get { return requiredVersion != null && requiredVersion > LauncherUpdater.Current; } }
    private bool RebuildRequired { get { return requiredVersion != null && !LauncherRequired && !currentBuildVerified; } }
    private bool PlayBlocked { get { return checkingUpdate || LauncherRequired || RebuildRequired; } }

    internal void StartUpdateChecks()
    {
        checkingUpdate = true;
        RefreshState();
        window.Loaded += async (s, e) => await CheckForUpdate(false, true);
        scheduledUpdate = new DispatcherTimer { Interval = TimeSpan.FromMinutes(15) };
        scheduledUpdate.Tick += async (s, e) => await CheckForUpdate(false);
        scheduledUpdate.Start();
        window.Closed += (s, e) => scheduledUpdate.Stop();
    }

    private async Task CheckForUpdate(bool retry, bool first = false)
    {
        if ((!first && checkingUpdate) || downloadingUpdate || busy || running != null) return;
        checkingUpdate = true;
        updateUnavailable = false;
        if (LauncherRequired) updateMessage = "Checking GitHub for launcher " + LauncherUpdater.DisplayVersion(requiredVersion) + "…";
        RefreshState();
        try {
            var latest = await Task.Run(() => LauncherUpdater.Check());
            if (latest != null && latest.Version > LauncherUpdater.Current &&
                (requiredVersion == null || latest.Version >= requiredVersion)) {
                if (requiredVersion == null || latest.Version > requiredVersion) {
                    requiredVersion = latest.Version;
                    currentBuildVerified = false;
                }
                core.RequireVersion(latest.Version);
                if (!retry && File.Exists(core.UpdateError)) {
                    updateMessage = File.ReadAllText(core.UpdateError) + " Close any other launcher window and choose Retry update.";
                    return;
                }
                downloadingUpdate = true;
                updateMessage = "Downloading and verifying launcher " + LauncherUpdater.DisplayVersion(latest.Version) + "…";
                RefreshState();
                await Task.Run(() => LauncherUpdater.StageAndRestart(core, latest));
                SavePreferences();
                Application.Current.Shutdown();
            } else if (LauncherRequired) {
                updateMessage = "The required launcher release could not be found on GitHub. Check your connection and retry.";
            }
        } catch (Exception error) {
            updateUnavailable = true;
            if (LauncherRequired) {
                updateMessage = "The required update could not be installed. " + error.Message;
            }
        } finally {
            checkingUpdate = false;
            downloadingUpdate = false;
            if (!window.Dispatcher.HasShutdownStarted) RefreshState();
        }
    }

    private void InitializeUpdateState()
    {
        requiredVersion = core.RequiredVersion();
        Version previous;
        if (Version.TryParse(Pref("launcher_version", ""), out previous) && previous < LauncherUpdater.Current &&
            (requiredVersion == null || requiredVersion < LauncherUpdater.Current)) {
            core.RequireVersion(LauncherUpdater.Current);
            requiredVersion = LauncherUpdater.Current;
        }
        currentBuildVerified = requiredVersion != null && !LauncherRequired && core.BuiltWith(LauncherUpdater.Current);
        Find<TextBlock>("HeaderVersion").Text = LauncherUpdater.DisplayVersion(LauncherUpdater.Current);
        Find<Button>("UpdateRetryButton").Click += async (s, e) => await CheckForUpdate(true);
        Click("RebuildButton", () => ShowPage(Rom));
    }

    private void RefreshUpdateControls()
    {
        Visible("UpdateShell", LauncherRequired);
        Visible("HomePage", page == Home && !LauncherRequired);
        Visible("WizardShell", IsWizard && !LauncherRequired);
        Visible("Steps", IsWizard && !LauncherRequired);
        Visible("SettingsShell", page >= Graphics && !LauncherRequired);
        Visible("RebuildPane", RebuildRequired);
        Visible("UpdateProgress", checkingUpdate || downloadingUpdate);
        Visible("UpdateRetryButton", LauncherRequired && !checkingUpdate && !downloadingUpdate);
        Find<TextBlock>("UpdateMessage").Text = String.IsNullOrWhiteSpace(updateMessage)
            ? "Connect to GitHub to download launcher " + (requiredVersion == null ? "" : LauncherUpdater.DisplayVersion(requiredVersion)) + "."
            : updateMessage;
        Find<TextBlock>("UpdateCheckNote").Text = checkingUpdate ? "Checking for launcher updates…" :
            updateUnavailable ? "Could not check for launcher updates. The check will be retried later." :
            "Launcher " + LauncherUpdater.DisplayVersion(LauncherUpdater.Current);
        Find<Button>("SettingsButton").IsEnabled = !busy && !LauncherRequired;
        Find<Button>("PlaySettingsButton").IsEnabled = !busy && !LauncherRequired;
    }
}
