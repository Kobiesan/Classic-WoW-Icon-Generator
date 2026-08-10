using System.Globalization;
using System.Security.Cryptography;

namespace WowIconForge.Core.Models;

/// <summary>Where a download has got to, for the wizard's progress bar.</summary>
public sealed record ModelDownloadProgress(
    string RelativePath,
    int FileIndex,
    int FileCount,
    long BytesRead,
    long TotalBytes,
    string Stage)
{
    /// <summary>Progress across the whole manifest, in [0, 1].</summary>
    public double Fraction
    {
        get
        {
            if (FileCount <= 0)
            {
                return 0d;
            }

            double perFile = 1d / FileCount;
            double withinFile = TotalBytes > 0
                ? Math.Clamp((double)BytesRead / TotalBytes, 0d, 1d)
                : 0d;
            return Math.Clamp((FileIndex * perFile) + (withinFile * perFile), 0d, 1d);
        }
    }

    public override string ToString() =>
        $"{Stage} {RelativePath} ({FileIndex + 1}/{FileCount})";
}

/// <summary>Per-file outcome of checking an existing model directory.</summary>
public sealed record ModelFileVerification(
    string RelativePath,
    bool Exists,
    bool HashMatches,
    bool WasChecked,
    string? ActualSha256 = null)
{
    /// <summary>True when the file is present and either verified or unpinned.</summary>
    public bool IsUsable => Exists && (HashMatches || !WasChecked);
}

public sealed record ModelVerificationResult(IReadOnlyList<ModelFileVerification> Files)
{
    public bool IsComplete => Files.All(file => file.IsUsable);

    public IEnumerable<ModelFileVerification> Missing => Files.Where(file => !file.Exists);

    public IEnumerable<ModelFileVerification> Corrupt =>
        Files.Where(file => file.Exists && file.WasChecked && !file.HashMatches);
}

/// <summary>
/// Fetches the model files named by a <see cref="ModelManifest"/> and verifies
/// them against their SHA-256.
/// </summary>
/// <remarks>
/// The models are several gigabytes, so they cannot live in the executable. The
/// installer can drop a <c>models</c> folder next to the exe, and where it does
/// not, this is what the first-run wizard uses instead.
/// <para>
/// Three things it is careful about, because this writes attacker-influenced
/// paths and multi-gigabyte files to a user's disk:
/// downloads land in a <c>.part</c> file and are only moved into place after the
/// hash matches, so an interrupted download can never masquerade as a good one;
/// unpinned entries are refused unless explicitly allowed, so "verify" means
/// something; and every destination path is re-checked against the target
/// directory even though the manifest already validated it.
/// </para>
/// </remarks>
public sealed class ModelDownloader
{
    private const int BufferSize = 81920;

    private readonly HttpClient _httpClient;
    private readonly bool _ownsHttpClient;

    public ModelDownloader(HttpClient? httpClient = null)
    {
        _ownsHttpClient = httpClient is null;
        _httpClient = httpClient ?? new HttpClient
        {
            // Model files are large; the default 100s covers the whole response.
            Timeout = TimeSpan.FromMinutes(30),
        };
    }

    /// <summary>
    /// Downloads everything the manifest lists that is not already present and
    /// verified.
    /// </summary>
    /// <param name="manifest">The files to fetch.</param>
    /// <param name="targetDirectory">Model directory to populate; created if absent.</param>
    /// <param name="progress">Optional per-chunk progress, for the wizard's bar.</param>
    /// <param name="allowUnpinned">
    /// Permit entries with no sha256. Off by default: an unverified download is
    /// exactly what the hash is there to prevent.
    /// </param>
    /// <param name="cancellationToken">Cancels mid-download; partial files are removed.</param>
    public async Task<ModelVerificationResult> DownloadAsync(
        ModelManifest manifest,
        string targetDirectory,
        IProgress<ModelDownloadProgress>? progress = null,
        bool allowUnpinned = false,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(manifest);
        ArgumentException.ThrowIfNullOrWhiteSpace(targetDirectory);

        if (!allowUnpinned)
        {
            string[] unpinned = manifest.UnpinnedFiles.Select(file => file.RelativePath).ToArray();
            if (unpinned.Length > 0)
            {
                throw new ModelDownloadException(
                    "These manifest entries have no sha256, so they cannot be verified: " +
                    string.Join(", ", unpinned) +
                    ". Add hashes to model-sources.json, or pass allowUnpinned to skip verification.");
            }
        }

        Directory.CreateDirectory(targetDirectory);

        var results = new List<ModelFileVerification>(manifest.Files.Count);

        for (int index = 0; index < manifest.Files.Count; index++)
        {
            cancellationToken.ThrowIfCancellationRequested();

            ModelSource file = manifest.Files[index];
            string destination = ResolveDestination(targetDirectory, file.RelativePath);

            if (File.Exists(destination))
            {
                ModelFileVerification existing = await VerifyFileAsync(destination, file, cancellationToken)
                    .ConfigureAwait(false);

                if (existing.IsUsable)
                {
                    // Already here and good: resuming a part-finished install
                    // must not re-download gigabytes.
                    progress?.Report(new ModelDownloadProgress(
                        file.RelativePath, index, manifest.Files.Count,
                        file.SizeBytes, file.SizeBytes, "Already present"));
                    results.Add(existing);
                    continue;
                }
            }

            await DownloadFileAsync(file, destination, index, manifest.Files.Count, progress, cancellationToken)
                .ConfigureAwait(false);

            results.Add(await VerifyFileAsync(destination, file, cancellationToken).ConfigureAwait(false));
        }

        return new ModelVerificationResult(results);
    }

    /// <summary>Checks an existing directory without downloading anything.</summary>
    public async Task<ModelVerificationResult> VerifyAsync(
        ModelManifest manifest,
        string targetDirectory,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(manifest);
        ArgumentException.ThrowIfNullOrWhiteSpace(targetDirectory);

        var results = new List<ModelFileVerification>(manifest.Files.Count);

        foreach (ModelSource file in manifest.Files)
        {
            cancellationToken.ThrowIfCancellationRequested();

            string destination = ResolveDestination(targetDirectory, file.RelativePath);
            results.Add(File.Exists(destination)
                ? await VerifyFileAsync(destination, file, cancellationToken).ConfigureAwait(false)
                : new ModelFileVerification(file.RelativePath, Exists: false, HashMatches: false, WasChecked: false));
        }

        return new ModelVerificationResult(results);
    }

    /// <summary>
    /// Computes a manifest from files already on disk, so a user who exported
    /// their own models can pin hashes without hand-computing them.
    /// </summary>
    public static async Task<ModelManifest> ComputeManifestAsync(
        ModelManifest template,
        string sourceDirectory,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(template);
        ArgumentException.ThrowIfNullOrWhiteSpace(sourceDirectory);

        var files = new List<ModelSource>(template.Files.Count);

        foreach (ModelSource file in template.Files)
        {
            string path = ResolveDestination(sourceDirectory, file.RelativePath);
            if (!File.Exists(path))
            {
                files.Add(file);
                continue;
            }

            await using FileStream stream = File.OpenRead(path);
            string hash = await ComputeSha256Async(stream, cancellationToken).ConfigureAwait(false);
            files.Add(file with { Sha256 = hash, SizeBytes = new FileInfo(path).Length });
        }

        return template with { Files = files };
    }

    public static async Task<string> ComputeSha256Async(
        Stream stream, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(stream);

        byte[] hash = await SHA256.HashDataAsync(stream, cancellationToken).ConfigureAwait(false);
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    private async Task DownloadFileAsync(
        ModelSource file,
        string destination,
        int index,
        int fileCount,
        IProgress<ModelDownloadProgress>? progress,
        CancellationToken cancellationToken)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(destination)!);

        // Download beside the destination, then move: a half-written file must
        // never be mistaken for a finished one on the next run.
        string partPath = destination + ".part";

        try
        {
            using HttpResponseMessage response = await _httpClient
                .GetAsync(file.Url, HttpCompletionOption.ResponseHeadersRead, cancellationToken)
                .ConfigureAwait(false);

            if (!response.IsSuccessStatusCode)
            {
                throw new ModelDownloadException(
                    $"Could not download {file.RelativePath}: the server returned " +
                    $"{(int)response.StatusCode} {response.ReasonPhrase}.");
            }

            long total = response.Content.Headers.ContentLength ?? file.SizeBytes;

            await using (Stream source = await response.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false))
            await using (FileStream target = File.Create(partPath))
            {
                var buffer = new byte[BufferSize];
                long read = 0;
                int count;

                progress?.Report(new ModelDownloadProgress(
                    file.RelativePath, index, fileCount, 0, total, "Downloading"));

                while ((count = await source.ReadAsync(buffer, cancellationToken).ConfigureAwait(false)) > 0)
                {
                    await target.WriteAsync(buffer.AsMemory(0, count), cancellationToken).ConfigureAwait(false);
                    read += count;
                    progress?.Report(new ModelDownloadProgress(
                        file.RelativePath, index, fileCount, read, total, "Downloading"));
                }
            }

            if (file.IsPinned)
            {
                progress?.Report(new ModelDownloadProgress(
                    file.RelativePath, index, fileCount, total, total, "Verifying"));

                await using FileStream written = File.OpenRead(partPath);
                string actual = await ComputeSha256Async(written, cancellationToken).ConfigureAwait(false);

                if (!string.Equals(actual, file.Sha256, StringComparison.OrdinalIgnoreCase))
                {
                    throw new ModelDownloadException(
                        $"{file.RelativePath} did not match its expected checksum. " +
                        $"Expected {file.Sha256}, got {actual}. The file was discarded; " +
                        "the download may have been corrupted or the source may have changed.");
                }
            }

            File.Move(partPath, destination, overwrite: true);
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException && !cancellationToken.IsCancellationRequested)
        {
            TryDelete(partPath);
            throw new ModelDownloadException(
                $"Could not download {file.RelativePath} from {file.Url}: {ex.Message}", ex);
        }
        catch
        {
            TryDelete(partPath);
            throw;
        }
    }

    private static async Task<ModelFileVerification> VerifyFileAsync(
        string path, ModelSource file, CancellationToken cancellationToken)
    {
        if (!file.IsPinned)
        {
            return new ModelFileVerification(
                file.RelativePath, Exists: true, HashMatches: false, WasChecked: false);
        }

        await using FileStream stream = File.OpenRead(path);
        string actual = await ComputeSha256Async(stream, cancellationToken).ConfigureAwait(false);

        return new ModelFileVerification(
            file.RelativePath,
            Exists: true,
            HashMatches: string.Equals(actual, file.Sha256, StringComparison.OrdinalIgnoreCase),
            WasChecked: true,
            actual);
    }

    /// <summary>
    /// Second line of defence behind the manifest's own validation: resolve the
    /// path and confirm it really is inside the target directory.
    /// </summary>
    internal static string ResolveDestination(string targetDirectory, string relativePath)
    {
        ModelManifest.ValidateRelativePath(relativePath);

        string root = Path.GetFullPath(targetDirectory);
        string combined = Path.GetFullPath(Path.Combine(
            root, relativePath.Replace('/', Path.DirectorySeparatorChar)));

        string rootWithSeparator = root.EndsWith(Path.DirectorySeparatorChar)
            ? root
            : root + Path.DirectorySeparatorChar;

        if (!combined.StartsWith(rootWithSeparator, StringComparison.Ordinal))
        {
            throw new ModelManifestException(
                $"'{relativePath}' resolves outside the model folder.");
        }

        return combined;
    }

    private static void TryDelete(string path)
    {
        try
        {
            if (File.Exists(path))
            {
                File.Delete(path);
            }
        }
        catch (IOException)
        {
            // Best effort: a stray .part file is not worth masking the real error.
        }
    }

    /// <summary>Human-readable size, for the wizard's "this will download 3.4 GB" line.</summary>
    public static string FormatBytes(long bytes)
    {
        string[] units = ["B", "KB", "MB", "GB", "TB"];
        double value = bytes;
        int unit = 0;

        while (value >= 1024 && unit < units.Length - 1)
        {
            value /= 1024;
            unit++;
        }

        return string.Create(CultureInfo.InvariantCulture, $"{value:0.#} {units[unit]}");
    }

    public void Dispose()
    {
        if (_ownsHttpClient)
        {
            _httpClient.Dispose();
        }
    }
}

public sealed class ModelDownloadException : Exception
{
    public ModelDownloadException(string message)
        : base(message)
    {
    }

    public ModelDownloadException(string message, Exception innerException)
        : base(message, innerException)
    {
    }
}
