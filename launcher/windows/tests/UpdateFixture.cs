using System.IO;
using System.Reflection;

internal static class UpdateFixture
{
    private static void Main()
    {
        File.WriteAllText("restarted-version.txt", Assembly.GetExecutingAssembly().GetName().Version.ToString());
    }
}
