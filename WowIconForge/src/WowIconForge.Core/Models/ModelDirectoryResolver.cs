using WowIconForge.Core.Inference;

namespace WowIconForge.Core.Models;

/// <summary>How the model directory in use was arrived at.</summary>
public enum ModelDirectorySource
{
    /// <summary>The user picked it, or the wizard saved it.</summary>
    Setting,

    /// <summary>A <c>models</c> folder the installer placed next to the executable.</summary>
    BundledWithInstall,

    /// <summary>The per-user default the wizard downloads into.</summary>
    UserData,
}

public sealed record ResolvedModelDirectory(
    string Path,
    ModelDirectorySource Source,
    ModelDirectoryStatus Status)
{
    public bool IsComplete => Status.IsComplete;

    public override string ToString() => $"{Path} ({Source})";
}

/// <summary>
/// Decides which model directory the app should use.
/// </summary>
/// <remarks>
/// This is what makes "bundle the models" and "download them on first run" the
/// same code path rather than two install-time variants. The installer may or
/// may not drop a <c>models</c> folder next to the executable; the app resolves
/// at startup, in order:
/// <list type="number">
/// <item>the configured directory, if it is set and complete;</item>
/// <item><c>&lt;app folder&gt;\models</c>, if the installer bundled one;</item>
/// <item><c>%LOCALAPPDATA%\WowIconForge\models</c>, the per-user download target.</item>
/// </list>
/// The download target is deliberately under LocalAppData rather than Program
/// Files: the app installs per-machine and would need elevation to write several
/// gigabytes into its own folder.
/// </remarks>
public sealed class ModelDirectoryResolver
{
    public const string ModelFolderName = "models";
    public const string ApplicationFolderName = "WowIconForge";

    private readonly string _applicationDirectory;
    private readonly string _localAppDataDirectory;

    public ModelDirectoryResolver(string? applicationDirectory = null, string? localAppDataDirectory = null)
    {
        _applicationDirectory = applicationDirectory ?? AppContext.BaseDirectory;
        _localAppDataDirectory = localAppDataDirectory
            ?? Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
    }

    /// <summary>Where the installer would have put a bundled copy.</summary>
    public string BundledDirectory => Path.Combine(_applicationDirectory, ModelFolderName);

    /// <summary>Where the first-run wizard downloads to.</summary>
    public string UserDataDirectory =>
        Path.Combine(_localAppDataDirectory, ApplicationFolderName, ModelFolderName);

    public ResolvedModelDirectory Resolve(string? configuredDirectory)
    {
        if (!string.IsNullOrWhiteSpace(configuredDirectory))
        {
            ModelDirectoryStatus configured = ModelLayout.Probe(configuredDirectory);
            if (configured.IsComplete)
            {
                return new ResolvedModelDirectory(
                    configuredDirectory, ModelDirectorySource.Setting, configured);
            }
        }

        ModelDirectoryStatus bundled = ModelLayout.Probe(BundledDirectory);
        if (bundled.IsComplete)
        {
            return new ResolvedModelDirectory(
                BundledDirectory, ModelDirectorySource.BundledWithInstall, bundled);
        }

        ModelDirectoryStatus userData = ModelLayout.Probe(UserDataDirectory);
        if (userData.IsComplete)
        {
            return new ResolvedModelDirectory(
                UserDataDirectory, ModelDirectorySource.UserData, userData);
        }

        // Nothing usable. Hand back whichever candidate the wizard should work
        // on: the user's own choice if they made one, otherwise the download
        // target, since that is the one the wizard can actually fill.
        if (!string.IsNullOrWhiteSpace(configuredDirectory))
        {
            return new ResolvedModelDirectory(
                configuredDirectory,
                ModelDirectorySource.Setting,
                ModelLayout.Probe(configuredDirectory));
        }

        return new ResolvedModelDirectory(
            UserDataDirectory, ModelDirectorySource.UserData, userData);
    }

    /// <summary>True when the app has no usable models and must show the wizard.</summary>
    public bool NeedsFirstRunWizard(string? configuredDirectory) =>
        !Resolve(configuredDirectory).IsComplete;
}
