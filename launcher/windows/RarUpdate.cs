using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Threading.Tasks;

internal static class RarUpdate
{
    private const string LauncherEntry = "SM3DL-Launcher.exe";
    private const string ReaderHash = "0d3715001790f0fd18d3e850f947b540530b2d2deb9a2e6a9e84f2ed7b234235";
    private static readonly byte[] Rar5 = { 0x52, 0x61, 0x72, 0x21, 0x1A, 0x07, 0x01, 0x00 };

    internal static void ExtractLauncher(string archive, string stage, string target)
    {
        using (var source = File.OpenRead(archive)) {
            foreach (byte marker in Rar5) if (source.ReadByte() != marker)
                throw new InvalidDataException("The update is not a standard RAR5 archive.");
        }

        string reader = Path.Combine(stage, "rar-reader.exe");
        using (var resource = Assembly.GetExecutingAssembly().GetManifestResourceStream("Update.UnRAR.exe"))
        using (var file = new FileStream(reader, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            resource.CopyTo(file);
        LauncherUpdater.ValidateHash(reader, ReaderHash);
        string quoted = LauncherCore.Quote(archive);
        using (var names = new MemoryStream()) {
            Run(reader, stage, "lb -cfg- -- " + quoted, names, 4096);
            if (Encoding.UTF8.GetString(names.ToArray()).TrimEnd('\r', '\n') != LauncherEntry)
                throw new InvalidDataException("Expected a RAR with only SM3DL-Launcher.exe at its root.");
        }

        // Print exactly the intended entry into a pipe. Archive paths are never used for writing files.
        using (var executable = new FileStream(target, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            Run(reader, stage, "p -inul -cfg- -- " + quoted + " " + LauncherEntry, executable, LauncherUpdater.MaxDownload);
    }

    private static void Run(string reader, string stage, string arguments, Stream output, long limit)
    {
        var start = new ProcessStartInfo(reader, arguments) {
            WorkingDirectory = stage, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardInput = true, RedirectStandardError = true
        };
        start.EnvironmentVariables.Remove("RAR");
        start.EnvironmentVariables.Remove("RARINISWITCHES");
        using (var child = Process.Start(start)) {
            if (child == null) throw new IOException("Could not start the embedded RAR reader.");
            child.StandardInput.Close();
            child.ErrorDataReceived += (sender, e) => {};
            child.BeginErrorReadLine();
            var read = Task.Run(() => LauncherUpdater.CopyLimit(child.StandardOutput.BaseStream, output, limit));
            if (!child.WaitForExit(15000)) {
                try { child.Kill(); } catch (InvalidOperationException) {}
                child.WaitForExit(2000);
                try { read.GetAwaiter().GetResult(); } catch (IOException) {}
                throw new IOException("Reading the launcher archive took too long.");
            }
            read.GetAwaiter().GetResult();
            if (child.ExitCode != 0) throw new InvalidDataException("The RAR reader could not verify or unpack the launcher archive.");
        }
    }
}
