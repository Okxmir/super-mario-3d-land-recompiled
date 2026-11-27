using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

internal sealed class LauncherCore
{
    internal const string GameName = "SuperMario3DLandRecompiled.exe";
    internal const string Revision = "152c905f57215af8e84398d677f7a221c3e3054e";
    internal static readonly string[] Languages = { "en", "fr", "de", "it", "es", "nl", "pt", "ru" };
    internal static readonly int[] LanguageIds = { 1, 2, 3, 4, 5, 8, 9, 10 };
    private static readonly string[] RequiredFiles = {
        GameName, "SDL3.dll", "SM3DL-EUR.cxi", "mii.romfs", "shared-font.bcfnt"
    };
    private static readonly Regex TextureName = new Regex(@"^tex1_[0-9]+x[0-9]+_[0-9a-fA-F]{16}_[0-9]+_mip0\.png$");
    private static readonly UTF8Encoding Utf8 = new UTF8Encoding(false);
    internal readonly string Root;
    internal string Game { get { return Path.Combine(Root, "Game"); } }
    internal string LocalExe { get { return Path.Combine(Game, GameName); } }
    internal string Log { get { return Path.Combine(Root, "build.log"); } }
    internal string Preferences { get { return Path.Combine(Root, "launcher.ini"); } }
    internal string Source { get { return Path.Combine(Root, "source-" + Revision); } }
    internal string UpdateState { get { return Path.Combine(Root, "required-update.ini"); } }
    internal string UpdateError { get { return Path.Combine(Root, "update-error.txt"); } }
    internal string BuildReceipt { get { return Path.Combine(Game, ".launcher-build.ini"); } }

    internal LauncherCore(string root) { Root = Path.GetFullPath(root); }

    internal static Dictionary<string, string> ReadSettings(string path)
    {
        var settings = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (!File.Exists(path)) return settings;
        foreach (string line in File.ReadAllLines(path, Utf8)) {
            int separator = line.IndexOf('=');
            if (separator > 0) settings[line.Substring(0, separator).Trim()] = line.Substring(separator + 1);
        }
        return settings;
    }

    internal static string Get(IDictionary<string, string> settings, string key, string fallback)
    {
        string result;
        return settings.TryGetValue(key, out result) ? result : fallback;
    }

    internal static void WriteSettings(string path, IDictionary<string, string> settings)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path));
        string temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try {
            File.WriteAllLines(temporary, settings.Select(pair => pair.Key + "=" + pair.Value), Utf8);
            if (File.Exists(path)) File.Replace(temporary, path, null);
            else File.Move(temporary, path);
        } finally {
            if (File.Exists(temporary)) File.Delete(temporary);
        }
    }

    internal static bool ValidGame(string path)
    {
        if (String.IsNullOrEmpty(path) || !String.Equals(Path.GetFileName(path), GameName, StringComparison.OrdinalIgnoreCase))
            return false;
        string folder = Path.GetDirectoryName(path);
        return !String.IsNullOrEmpty(folder) && RequiredFiles.All(name => File.Exists(Path.Combine(folder, name)));
    }

    internal string Profile(string exe)
    {
        if (String.Equals(exe, LocalExe, StringComparison.OrdinalIgnoreCase))
            return Path.Combine(Game, "userdata");
        using (var sha = SHA256.Create()) {
            byte[] hash = sha.ComputeHash(Utf8.GetBytes(Path.GetFullPath(exe).ToUpperInvariant()));
            return Path.Combine(Root, "profiles", BitConverter.ToString(hash, 0, 12).Replace("-", "").ToLowerInvariant());
        }
    }

    internal string SaveProfile(string exe, string linkedSource)
    {
        return String.Equals(exe, LocalExe, StringComparison.OrdinalIgnoreCase) &&
            !String.IsNullOrEmpty(linkedSource) && Path.IsPathRooted(linkedSource) &&
            String.Equals(Path.GetFileName(linkedSource), GameName, StringComparison.OrdinalIgnoreCase)
            ? Profile(linkedSource) : Profile(exe);
    }

    internal Version RequiredVersion()
    {
        Version result;
        return Version.TryParse(Get(ReadSettings(UpdateState), "launcher_version", ""), out result) ? result : null;
    }

    internal void RequireVersion(Version version)
    {
        var previous = RequiredVersion();
        if (previous == null || version > previous)
            WriteSettings(UpdateState, new Dictionary<string, string> { { "launcher_version", version.ToString() } });
    }

    internal bool BuiltWith(Version version)
    {
        var receipt = ReadSettings(BuildReceipt);
        return ValidGame(LocalExe) && Get(receipt, "revision", "") == Revision &&
            Get(receipt, "launcher_version", "") == version.ToString() &&
            String.Equals(Get(receipt, "exe_sha256", ""), LauncherUpdater.HashFile(LocalExe), StringComparison.OrdinalIgnoreCase);
    }

    internal void RecordBuild()
    {
        if (!ValidGame(LocalExe)) throw new IOException("The completed build is missing game files.");
        WriteSettings(BuildReceipt, new Dictionary<string, string> {
            { "revision", Revision }, { "launcher_version", LauncherUpdater.Current.ToString() },
            { "exe_sha256", LauncherUpdater.HashFile(LocalExe) }
        });
    }

    internal static bool HasPack(string profile, int quality)
    {
        if (quality == 0) return true;
        if (String.IsNullOrEmpty(profile)) return false;
        string folder = Path.Combine(profile, "hd-textures", quality == 2 ? "sm3dl-4k-1.2.0b" : "sm3dl-1080p-1.2.0b");
        try {
            return Directory.Exists(folder) && Directory.EnumerateFiles(folder, "*.png")
                .Where(p => TextureName.IsMatch(Path.GetFileName(p))).Count() == 297;
        } catch (IOException) { return false; }
        catch (UnauthorizedAccessException) { return false; }
    }

    internal ProcessStartInfo GameStart(string exe, IDictionary<string, string> graphics, string linkedSource = "")
    {
        if (!ValidGame(exe)) throw new FileNotFoundException("Game or companion files not found.", exe);
        string profile = Profile(exe);
        string path = Path.Combine(profile, "settings.ini");
        var settings = ReadSettings(path);
        foreach (var pair in graphics) settings[pair.Key] = pair.Value;
        WriteSettings(path, settings);
        var start = new ProcessStartInfo(exe);
        start.UseShellExecute = false;
        start.WorkingDirectory = Path.GetDirectoryName(exe);
        start.EnvironmentVariables["SM3DL_DATA_DIR"] = profile;
        start.EnvironmentVariables["SM3DL_SAVE_DIR"] = SaveProfile(exe, linkedSource);
        return start;
    }

    internal void InstallSources()
    {
        string marker = Path.Combine(Source, ".launcher-ready");
        if (File.Exists(marker) && File.Exists(Path.Combine(Source, "scripts", "build_game.ps1"))) return;
        Directory.CreateDirectory(Source);
        string prefix = Source + Path.DirectorySeparatorChar;
        using (Stream bytes = Assembly.GetExecutingAssembly().GetManifestResourceStream("GameSources.zip"))
        using (var zip = new ZipArchive(bytes, ZipArchiveMode.Read)) {
            foreach (ZipArchiveEntry entry in zip.Entries) {
                string target = Path.GetFullPath(Path.Combine(Source, entry.FullName));
                if (!target.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("Unexpected source archive path.");
                if (entry.Name.Length == 0) {
                    Directory.CreateDirectory(target);
                    continue;
                }
                Directory.CreateDirectory(Path.GetDirectoryName(target));
                using (Stream input = entry.Open())
                using (var output = new FileStream(target, FileMode.Create, FileAccess.Write)) input.CopyTo(output);
            }
        }
        File.WriteAllText(marker, Revision, Utf8);
    }

    internal bool Build(string rom, string language, bool pack1080, bool pack4K, Action<string> line)
    {
        Directory.CreateDirectory(Root);
        using (var held = new FileStream(Path.Combine(Root, "build.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None))
        using (var output = new StreamWriter(Log, false, Utf8)) {
            Action<string> report = value => {
                lock (output) {
                    output.WriteLine(value);
                    output.Flush();
                    line(value);
                }
            };
            report("Launcher / source " + Revision);
            InstallSources();
            string powershell = Path.Combine(Environment.SystemDirectory, "WindowsPowerShell", "v1.0", "powershell.exe");
            string script = Path.Combine(Source, "scripts", "build_game.ps1");
            var compile = StartInfo(powershell, "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "
                + Quote(script) + " -Portable -Cartridge " + Quote(rom)
                + " -Language " + Quote(language) + " -OutputDirectory " + Quote(Game), Source);
            if (Run(compile, report) != 0 || !ValidGame(LocalExe))
                throw new InvalidOperationException("Build failed. See build.log.");
            bool warnings = false;
            if (pack1080 || pack4K) {
                report("Build stage: Installing HD textures");
                string python = Path.Combine(Source, "build", "p", "python", "python.exe");
                string args = "-u " + Quote(Path.Combine(Source, "tools", "hd_pack.py")) + " " + Quote(Game);
                foreach (int quality in new[] { 1, 2 }) {
                    if (!(quality == 1 ? pack1080 : pack4K)) continue;
                    try { warnings |= Run(StartInfo(python, args + (quality == 2 ? " --4k" : ""), Source), report) != 0; }
                    catch (System.ComponentModel.Win32Exception error) { report("HD: " + error.Message); warnings = true; }
                }
            }
            report(warnings ? "Game ready (HD download warning)." : "Game ready.");
            return warnings;
        }
    }

    private static ProcessStartInfo StartInfo(string program, string args, string cwd)
    {
        var start = new ProcessStartInfo(program, args) {
            WorkingDirectory = cwd, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = Utf8, StandardErrorEncoding = Utf8,
        };
        start.EnvironmentVariables["NINJA_STATUS"] = "[%f/%t] ";
        start.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
        return start;
    }

    private static int Run(ProcessStartInfo start, Action<string> report)
    {
        using (var process = new Process { StartInfo = start }) {
            DataReceivedEventHandler handler = (sender, args) => { if (args.Data != null) report(args.Data); };
            process.OutputDataReceived += handler;
            process.ErrorDataReceived += handler;
            if (!process.Start()) throw new InvalidOperationException("Could not start " + start.FileName);
            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            process.WaitForExit();
            return process.ExitCode;
        }
    }

    internal static string Quote(string value)
    {
        return "\"" + Regex.Replace(value, @"(\\*)(""|$)", m =>
            new string('\\', m.Groups[1].Length * 2 + (m.Groups[2].Length == 0 ? 0 : 1)) + m.Groups[2]) + "\"";
    }

    internal static string Number(double value) { return value.ToString("0", CultureInfo.InvariantCulture); }
}
