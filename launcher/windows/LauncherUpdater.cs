using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;

[assembly: AssemblyVersion(LauncherUpdater.VersionText)]
[assembly: AssemblyFileVersion(LauncherUpdater.VersionText)]

internal sealed class LauncherUpdater
{
    internal const string VersionText = "1.1.7.0";
    internal const string Repo = "Okxmir/super-mario-3d-land-recompiled";
    internal const string ReleasesUrl = "https://api.github.com/repos/" + Repo + "/releases?per_page=20";
    internal static readonly Version Current = new Version(VersionText);
    internal const long MaxDownload = 32 * 1024 * 1024;
    private static readonly Regex ExeAssetName = new Regex(@"^SM3DL-Launcher-v([0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5})\.exe$", RegexOptions.CultureInvariant);
    private static readonly Regex RarAssetName = new Regex(@"^(?:Super-Mario-3D-Land|SM3DL-Launcher)-Windows-x64-v([0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5})\.rar$", RegexOptions.CultureInvariant);
    private static readonly Regex Hex = new Regex(@"^[0-9a-fA-F]{64}$", RegexOptions.CultureInvariant);
    private static readonly Regex SafeTag = new Regex(@"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$", RegexOptions.CultureInvariant);
    internal static string DisplayVersion(Version version) { return version.ToString(3); }

    internal sealed class Candidate
    {
        internal Version Version;
        internal string Sha256;
        internal Uri Url;
        internal long Size;
        internal bool IsArchive;
    }

    public sealed class Release
    {
        public string tag_name { get; set; }
        public bool draft { get; set; }
        public bool prerelease { get; set; }
        public Asset[] assets { get; set; }
    }
    public sealed class Asset
    {
        public string name { get; set; }
        public string state { get; set; }
        public string digest { get; set; }
        public string browser_download_url { get; set; }
        public long size { get; set; }
    }

    internal static Candidate ParseReleases(string json)
    {
        var serializer = new JavaScriptSerializer { MaxJsonLength = 2 * 1024 * 1024 };
        Release[] releases = serializer.Deserialize<Release[]>(json);
        if (releases == null) throw new InvalidDataException("Invalid GitHub release list.");
        Candidate best = null;
        foreach (var release in releases) {
            if (release == null || release.draft || release.prerelease || !SafeTag.IsMatch(release.tag_name ?? "")) continue;
            foreach (var asset in release.assets ?? new Asset[0]) {
                if (asset == null || asset.state != "uploaded") continue;
                var match = RarAssetName.Match(asset.name ?? "");
                bool archive = match.Success;
                if (!archive) match = ExeAssetName.Match(asset.name ?? "");
                if (!match.Success || asset.size <= 0 || asset.size > MaxDownload) continue;
                var version = new Version(match.Groups[1].Value + ".0");
                if (best != null && (version < best.Version || version == best.Version && (!archive || best.IsArchive))) continue;
                string digest = asset.digest ?? "";
                if (!digest.StartsWith("sha256:", StringComparison.Ordinal) || !Hex.IsMatch(digest.Substring(7))) continue;
                string url = "https://github.com/" + Repo + "/releases/download/" + release.tag_name + "/" + asset.name;
                if (!String.Equals(url, asset.browser_download_url, StringComparison.Ordinal)) continue;
                best = new Candidate { Version = version, Sha256 = digest.Substring(7), Url = new Uri(url), Size = asset.size, IsArchive = archive };
            }
        }
        return best;
    }

    internal static Candidate Check()
    {
        var request = Request(new Uri(ReleasesUrl), "application/vnd.github+json", 6500);
        request.Headers["X-GitHub-Api-Version"] = "2022-11-28";
        using (var response = (HttpWebResponse)request.GetResponse())
        using (var data = new MemoryStream()) {
            CopyLimit(response.GetResponseStream(), data, 2 * 1024 * 1024);
            return ParseReleases(Encoding.UTF8.GetString(data.ToArray()));
        }
    }

    private static HttpWebRequest Request(Uri uri, string accept, int timeout)
    {
        ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;
        var request = (HttpWebRequest)WebRequest.Create(uri);
        request.UserAgent = "SM3DL-Launcher/" + DisplayVersion(Current);
        request.Accept = accept;
        request.AllowAutoRedirect = false;
        request.Timeout = timeout;
        request.ReadWriteTimeout = timeout;
        request.AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate;
        return request;
    }

    private static bool TrustedAssetHost(Uri uri)
    {
        return uri.Scheme == "https" && uri.IsDefaultPort && uri.UserInfo.Length == 0 &&
            (uri.Host == "github.com" || uri.Host == "release-assets.githubusercontent.com" || uri.Host == "objects.githubusercontent.com");
    }

    private static void Download(Candidate candidate, string destination)
    {
        Uri uri = candidate.Url;
        for (int hops = 0; hops < 5; hops++) {
            if (!TrustedAssetHost(uri)) throw new InvalidDataException("Update redirected outside GitHub.");
            using (var response = (HttpWebResponse)Request(uri, "application/octet-stream", 15000).GetResponse()) {
                int status = (int)response.StatusCode;
                if (status >= 300 && status < 400) {
                    string location = response.Headers["Location"];
                    if (String.IsNullOrEmpty(location)) throw new InvalidDataException("Missing GitHub download location.");
                    uri = new Uri(uri, location);
                    continue;
                }
                using (var stream = new FileStream(destination, FileMode.CreateNew, FileAccess.Write, FileShare.None)) {
                    if (status != 200 || CopyLimit(response.GetResponseStream(), stream, candidate.Size) != candidate.Size)
                        throw new InvalidDataException("Incomplete launcher download.");
                }
                return;
            }
        }
        throw new InvalidDataException("Too many GitHub download redirects.");
    }

    internal static long CopyLimit(Stream source, Stream destination, long max)
    {
        using (source) {
            var buffer = new byte[32768];
            long total = 0;
            int count;
            while ((count = source.Read(buffer, 0, buffer.Length)) != 0) {
                total += count;
                if (total > max) throw new InvalidDataException("The update exceeded its expected size.");
                destination.Write(buffer, 0, count);
            }
            return total;
        }
    }

    internal static string HashFile(string path)
    {
        using (var hash = SHA256.Create())
        using (var file = File.OpenRead(path))
            return BitConverter.ToString(hash.ComputeHash(file)).Replace("-", "").ToLowerInvariant();
    }

    internal static void ValidateHash(string path, string sha256)
    {
        if (!Hex.IsMatch(sha256 ?? "") || !String.Equals(HashFile(path), sha256, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("The update file did not match its SHA-256.");
    }

    internal static void ValidateBinary(string path, Version version, string sha256)
    {
        ValidateHash(path, sha256);
        var assembly = AssemblyName.GetAssemblyName(path);
        if (assembly.Name != typeof(LauncherUpdater).Assembly.GetName().Name || assembly.Version != version)
            throw new InvalidDataException("The file is not the advertised version of this launcher.");
    }

    internal static string PrepareUpdate(Candidate candidate, string payload, string stage)
    {
        if (candidate.Version <= Current) throw new InvalidOperationException("The launcher cannot downgrade.");
        long size = new FileInfo(payload).Length;
        if (size <= 0 || size > MaxDownload || size != candidate.Size)
            throw new InvalidDataException("The update file did not match the expected download size.");
        ValidateHash(payload, candidate.Sha256);
        string executable = Path.Combine(stage, "download.exe");
        if (candidate.IsArchive) RarUpdate.ExtractLauncher(payload, stage, executable);
        else if (!String.Equals(payload, executable, StringComparison.OrdinalIgnoreCase)) File.Copy(payload, executable);
        string executableHash = candidate.IsArchive ? HashFile(executable) : candidate.Sha256;
        ValidateBinary(executable, candidate.Version, executableHash);
        return executableHash;
    }

    internal static void StageAndRestart(LauncherCore core, Candidate candidate)
    {
        if (candidate.Version <= Current) throw new InvalidOperationException("The launcher cannot downgrade.");
        string current = Assembly.GetExecutingAssembly().Location;
        string stage = Path.Combine(core.Root, "updates", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(stage);
        string payload = Path.Combine(stage, candidate.IsArchive ? "release.rar" : "download.exe");
        Download(candidate, payload);
        var executableHash = PrepareUpdate(candidate, payload, stage);
        string helper = Path.Combine(stage, "finish-update.exe");
        File.Copy(current, helper);
        using (var child = Process.Start(new ProcessStartInfo(helper, "--finish-update " +
            Process.GetCurrentProcess().Id + " " + LauncherCore.Quote(Path.GetFileName(current)) + " " +
            candidate.Version + " " + executableHash) { UseShellExecute = false, WorkingDirectory = stage })) {
            if (child == null) throw new IOException("Could not start the launcher update helper.");
        }
    }

    internal static void Finish(string[] args)
    {
        string stage = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        var stageDirectory = new DirectoryInfo(stage);
        var data = stageDirectory.Parent == null ? null : stageDirectory.Parent.Parent;
        int pid;
        Version version;
        if (args.Length != 5 || data == null || data.Name != "LauncherData" || stageDirectory.Parent.Name != "updates" ||
            !Regex.IsMatch(stageDirectory.Name, @"^[0-9a-f]{32}$") ||
            !Int32.TryParse(args[1], out pid) || pid <= 0 ||
            !Version.TryParse(args[3], out version) || version <= Current || !Hex.IsMatch(args[4]) ||
            Path.GetFileName(args[2]) != args[2] || !args[2].EndsWith(".exe", StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Invalid update handoff.");

        string target = Path.Combine(data.Parent.FullName, args[2]);
        string newExe = Path.Combine(stage, "download.exe");
        string backup = Path.Combine(stage, "previous.backup");
        string errorPath = Path.Combine(data.FullName, "update-error.txt");
        try {
            Process parent = null;
            try { parent = Process.GetProcessById(pid); } catch (ArgumentException) {}
            if (parent != null) using (parent) {
                if (!parent.HasExited && (!String.Equals(parent.MainModule.FileName, target, StringComparison.OrdinalIgnoreCase) ||
                    !parent.WaitForExit(20000))) throw new IOException("Close other windows of this launcher and retry.");
            }
            ReplaceVerified(target, newExe, backup, version, args[4]);
            if (File.Exists(errorPath)) File.Delete(errorPath);
            try { OpenUpdated(target); }
            catch {
                File.Replace(backup, target, null);
                throw;
            }
        } catch (Exception error) {
            File.WriteAllText(errorPath, error.Message);
            OpenUpdated(target);
        }
    }

    private static void OpenUpdated(string target)
    {
        using (var child = Process.Start(new ProcessStartInfo(target) {
            UseShellExecute = false, WorkingDirectory = Path.GetDirectoryName(target)
        })) if (child == null) throw new IOException("Could not reopen the launcher.");
    }

    internal static void ReplaceVerified(string target, string staged, string backup, Version version, string digest)
    {
        var old = AssemblyName.GetAssemblyName(target);
        if (old.Name != typeof(LauncherUpdater).Assembly.GetName().Name || old.Version >= version)
            throw new IOException("The installed launcher has changed. Open the newest copy.");
        ValidateBinary(staged, version, digest);
        File.Replace(staged, target, backup);
    }
}
