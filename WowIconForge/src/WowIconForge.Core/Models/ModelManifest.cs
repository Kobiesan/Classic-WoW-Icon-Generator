using System.Text.Json;
using System.Text.Json.Serialization;

namespace WowIconForge.Core.Models;

/// <summary>One downloadable model file, with the hash it must match.</summary>
/// <param name="RelativePath">Destination under the model directory, forward slashes.</param>
/// <param name="Url">Absolute http(s) URL to fetch it from.</param>
/// <param name="Sha256">
/// Expected SHA-256, 64 hex characters. Null or empty means "not pinned", which
/// the downloader refuses by default - see <see cref="ModelDownloader"/>.
/// </param>
/// <param name="SizeBytes">Expected size, used for progress and a cheap sanity check. Zero if unknown.</param>
public sealed record ModelSource(
    string RelativePath,
    string Url,
    string? Sha256 = null,
    long SizeBytes = 0)
{
    [JsonIgnore]
    public bool IsPinned => !string.IsNullOrWhiteSpace(Sha256);
}

/// <summary>
/// The list of model files the first-run wizard can fetch, read from
/// <c>model-sources.json</c> shipped alongside the application.
/// </summary>
/// <remarks>
/// Kept as data rather than code so a user can point the app at their own
/// export, a mirror, or a different Stable Diffusion checkpoint without a
/// rebuild. Everything in it is validated on load: a manifest is untrusted
/// input, and it names paths that get written to disk.
/// </remarks>
public sealed record ModelManifest(
    string Name,
    string Description,
    IReadOnlyList<ModelSource> Files)
{
    public const string DefaultFileName = "model-sources.json";

    private static readonly JsonSerializerOptions SerializerOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        PropertyNameCaseInsensitive = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true,
        WriteIndented = true,
    };

    /// <summary>Total bytes to fetch, as far as the manifest declares.</summary>
    public long TotalBytes => Files.Sum(file => file.SizeBytes);

    public IEnumerable<ModelSource> UnpinnedFiles => Files.Where(file => !file.IsPinned);

    public static ModelManifest Parse(string json)
    {
        ArgumentNullException.ThrowIfNull(json);

        ModelManifest? manifest;
        try
        {
            manifest = JsonSerializer.Deserialize<ModelManifest>(json, SerializerOptions);
        }
        catch (JsonException ex)
        {
            throw new ModelManifestException($"The model manifest is not valid JSON: {ex.Message}", ex);
        }

        if (manifest is null)
        {
            throw new ModelManifestException("The model manifest is empty.");
        }

        Validate(manifest);
        return manifest;
    }

    public static ModelManifest Load(string path)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);

        if (!File.Exists(path))
        {
            throw new ModelManifestException($"No model manifest at {path}.");
        }

        return Parse(File.ReadAllText(path));
    }

    /// <summary>
    /// Finds the manifest shipped next to the executable, or null if absent.
    /// </summary>
    public static ModelManifest? LoadFromApplicationDirectory(string? baseDirectory = null)
    {
        string path = Path.Combine(baseDirectory ?? AppContext.BaseDirectory, DefaultFileName);
        return File.Exists(path) ? Load(path) : null;
    }

    public string ToJson() => JsonSerializer.Serialize(this, SerializerOptions);

    private static void Validate(ModelManifest manifest)
    {
        if (manifest.Files is null || manifest.Files.Count == 0)
        {
            throw new ModelManifestException("The model manifest lists no files.");
        }

        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        foreach (ModelSource file in manifest.Files)
        {
            if (string.IsNullOrWhiteSpace(file.RelativePath))
            {
                throw new ModelManifestException("A manifest entry has no relative path.");
            }

            ValidateRelativePath(file.RelativePath);

            if (!seen.Add(file.RelativePath))
            {
                throw new ModelManifestException($"Duplicate manifest entry for '{file.RelativePath}'.");
            }

            if (!Uri.TryCreate(file.Url, UriKind.Absolute, out Uri? uri) ||
                (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps))
            {
                throw new ModelManifestException(
                    $"'{file.RelativePath}' needs an absolute http or https URL, got '{file.Url}'.");
            }

            if (file.IsPinned && !IsSha256Hex(file.Sha256!))
            {
                throw new ModelManifestException(
                    $"'{file.RelativePath}' has a sha256 that is not 64 hex characters.");
            }

            if (file.SizeBytes < 0)
            {
                throw new ModelManifestException($"'{file.RelativePath}' has a negative size.");
            }
        }
    }

    /// <summary>
    /// Rejects anything that could escape the model directory. A manifest can
    /// come from anywhere, and it names files that get written to disk, so an
    /// entry like <c>../../Startup/evil.exe</c> must never be honoured.
    /// </summary>
    internal static void ValidateRelativePath(string relativePath)
    {
        if (Path.IsPathRooted(relativePath) || relativePath.Contains(':', StringComparison.Ordinal))
        {
            throw new ModelManifestException($"'{relativePath}' must be a relative path.");
        }

        string[] segments = relativePath.Split(new[] { '/', '\\' }, StringSplitOptions.None);

        foreach (string segment in segments)
        {
            if (segment.Length == 0)
            {
                throw new ModelManifestException($"'{relativePath}' has an empty path segment.");
            }

            if (segment is "." or "..")
            {
                throw new ModelManifestException(
                    $"'{relativePath}' must not navigate outside the model folder.");
            }
        }
    }

    private static bool IsSha256Hex(string value) =>
        value.Length == 64 && value.All(Uri.IsHexDigit);
}

public sealed class ModelManifestException : Exception
{
    public ModelManifestException(string message)
        : base(message)
    {
    }

    public ModelManifestException(string message, Exception innerException)
        : base(message, innerException)
    {
    }
}
