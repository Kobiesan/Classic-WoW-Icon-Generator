using System.Net;
using System.Text;
using WowIconForge.Core.Models;
using Xunit;

namespace WowIconForge.Core.Tests;

public class ModelManifestTests
{
    private const string ValidHash = "0000000000000000000000000000000000000000000000000000000000000000";

    private static string Json(string files) =>
        $$"""
        { "name": "test", "description": "d", "files": [ {{files}} ] }
        """;

    [Fact]
    public void ParsesAWellFormedManifest()
    {
        ModelManifest manifest = ModelManifest.Parse(Json(
            $$"""{ "relativePath": "unet/model.onnx", "url": "https://example.com/u", "sha256": "{{ValidHash}}", "sizeBytes": 1234 }"""));

        Assert.Equal("test", manifest.Name);
        ModelSource file = Assert.Single(manifest.Files);
        Assert.Equal("unet/model.onnx", file.RelativePath);
        Assert.True(file.IsPinned);
        Assert.Equal(1234, manifest.TotalBytes);
    }

    [Fact]
    public void UnpinnedEntriesAreAllowedButFlagged()
    {
        ModelManifest manifest = ModelManifest.Parse(Json(
            """{ "relativePath": "unet/model.onnx", "url": "https://example.com/u" }"""));

        Assert.False(manifest.Files[0].IsPinned);
        Assert.Single(manifest.UnpinnedFiles);
    }

    [Theory]
    [InlineData("../evil.exe")]
    [InlineData("unet/../../evil.exe")]
    [InlineData("./evil.exe")]
    [InlineData("/etc/passwd")]
    [InlineData(@"C:\Windows\evil.exe")]
    [InlineData(@"..\..\startup\evil.exe")]
    public void PathsThatEscapeTheModelFolderAreRejected(string relativePath)
    {
        // A manifest is untrusted input that names files written to disk.
        string json = Json($$"""{ "relativePath": "{{relativePath.Replace("\\", "\\\\")}}", "url": "https://example.com/u" }""");

        Assert.Throws<ModelManifestException>(() => ModelManifest.Parse(json));
    }

    [Fact]
    public void EmptyPathSegmentsAreRejected()
    {
        Assert.Throws<ModelManifestException>(() => ModelManifest.Parse(Json(
            """{ "relativePath": "unet//model.onnx", "url": "https://example.com/u" }""")));
    }

    [Theory]
    [InlineData("ftp://example.com/x")]
    [InlineData("file:///etc/passwd")]
    [InlineData("not-a-url")]
    [InlineData("")]
    public void NonHttpUrlsAreRejected(string url)
    {
        Assert.Throws<ModelManifestException>(() => ModelManifest.Parse(Json(
            $$"""{ "relativePath": "unet/model.onnx", "url": "{{url}}" }""")));
    }

    [Fact]
    public void MalformedHashesAreRejected()
    {
        Assert.Throws<ModelManifestException>(() => ModelManifest.Parse(Json(
            """{ "relativePath": "a.onnx", "url": "https://example.com/u", "sha256": "abc" }""")));
        Assert.Throws<ModelManifestException>(() => ModelManifest.Parse(Json(
            """{ "relativePath": "a.onnx", "url": "https://example.com/u", "sha256": "zzzz000000000000000000000000000000000000000000000000000000000000" }""")));
    }

    [Fact]
    public void DuplicateEntriesAreRejected()
    {
        Assert.Throws<ModelManifestException>(() => ModelManifest.Parse(Json(
            """
            { "relativePath": "a.onnx", "url": "https://example.com/1" },
            { "relativePath": "A.ONNX", "url": "https://example.com/2" }
            """)));
    }

    [Fact]
    public void EmptyFileListIsRejected()
    {
        Assert.Throws<ModelManifestException>(() =>
            ModelManifest.Parse("""{ "name": "x", "description": "y", "files": [] }"""));
    }

    [Fact]
    public void InvalidJsonGivesAReadableError()
    {
        ModelManifestException error = Assert.Throws<ModelManifestException>(() =>
            ModelManifest.Parse("{ not json"));

        Assert.Contains("not valid JSON", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void CommentsAndTrailingCommasAreTolerated()
    {
        // The file is meant to be hand-edited, so it should survive being
        // annotated the way a person actually annotates JSON.
        ModelManifest manifest = ModelManifest.Parse("""
            {
              "name": "test",
              "description": "d",
              // a comment
              "files": [
                { "relativePath": "unet/model.onnx", "url": "https://example.com/u" },
              ]
            }
            """);

        Assert.Single(manifest.Files);
    }

    [Fact]
    public void RoundTripsThroughJson()
    {
        ModelManifest original = ModelManifest.Parse(Json(
            $$"""{ "relativePath": "unet/model.onnx", "url": "https://example.com/u", "sha256": "{{ValidHash}}", "sizeBytes": 5 }"""));

        ModelManifest reparsed = ModelManifest.Parse(original.ToJson());

        // Compared element-wise on purpose: the compiler-generated record
        // equality uses reference equality for the IReadOnlyList member, so
        // Assert.Equal(original, reparsed) would fail even when every value
        // matches.
        Assert.Equal(original.Name, reparsed.Name);
        Assert.Equal(original.Description, reparsed.Description);
        Assert.Equal(original.Files, reparsed.Files);
    }

    [Fact]
    public void LoadReportsAMissingFileClearly()
    {
        ModelManifestException error = Assert.Throws<ModelManifestException>(() =>
            ModelManifest.Load(Path.Combine(Path.GetTempPath(), "definitely-absent.json")));

        Assert.Contains("No model manifest", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void ShippedManifestIsValidAndCoversEveryRequiredModelFile()
    {
        // The manifest is copied next to the test assembly by the csproj.
        ModelManifest? manifest = ModelManifest.LoadFromApplicationDirectory();

        Assert.NotNull(manifest);
        foreach (Core.Inference.ModelFile required in Core.Inference.ModelLayout.RequiredFiles)
        {
            Assert.Contains(manifest!.Files, file =>
                file.RelativePath.Equals(required.RelativePath, StringComparison.OrdinalIgnoreCase));
        }
    }
}

public class ModelDownloaderTests
{
    private static readonly byte[] Payload = Encoding.UTF8.GetBytes("pretend this is a 3 GB unet");

    private static string HashOf(byte[] bytes) =>
        Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(bytes)).ToLowerInvariant();

    private static ModelManifest ManifestFor(
        string relativePath = "unet/model.onnx", string? sha256 = null, byte[]? payload = null)
    {
        payload ??= Payload;
        return new ModelManifest("test", "d", [
            new ModelSource(relativePath, "https://example.com/unet", sha256 ?? HashOf(payload), payload.Length),
        ]);
    }

    [Fact]
    public async Task DownloadsAndVerifiesAFile()
    {
        using var temp = new TempDirectory();
        using var http = new HttpClient(new StubHandler(Payload));
        var downloader = new ModelDownloader(http);

        ModelVerificationResult result = await downloader.DownloadAsync(ManifestFor(), temp.Path);

        Assert.True(result.IsComplete);
        string written = Path.Combine(temp.Path, "unet", "model.onnx");
        Assert.True(File.Exists(written));
        Assert.Equal(Payload, await File.ReadAllBytesAsync(written));
    }

    [Fact]
    public async Task ChecksumMismatchDiscardsTheFile()
    {
        using var temp = new TempDirectory();
        using var http = new HttpClient(new StubHandler(Encoding.UTF8.GetBytes("corrupted")));
        var downloader = new ModelDownloader(http);

        ModelDownloadException error = await Assert.ThrowsAsync<ModelDownloadException>(() =>
            downloader.DownloadAsync(ManifestFor(), temp.Path));

        Assert.Contains("did not match its expected checksum", error.Message, StringComparison.Ordinal);
        Assert.False(File.Exists(Path.Combine(temp.Path, "unet", "model.onnx")));
        Assert.Empty(Directory.GetFiles(temp.Path, "*.part", SearchOption.AllDirectories));
    }

    [Fact]
    public async Task UnpinnedEntriesAreRefusedByDefault()
    {
        using var temp = new TempDirectory();
        using var http = new HttpClient(new StubHandler(Payload));
        var downloader = new ModelDownloader(http);
        var manifest = new ModelManifest("t", "d", [
            new ModelSource("unet/model.onnx", "https://example.com/unet"),
        ]);

        ModelDownloadException error = await Assert.ThrowsAsync<ModelDownloadException>(() =>
            downloader.DownloadAsync(manifest, temp.Path));

        Assert.Contains("cannot be verified", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task UnpinnedEntriesCanBeAllowedExplicitly()
    {
        using var temp = new TempDirectory();
        using var http = new HttpClient(new StubHandler(Payload));
        var downloader = new ModelDownloader(http);
        var manifest = new ModelManifest("t", "d", [
            new ModelSource("unet/model.onnx", "https://example.com/unet"),
        ]);

        ModelVerificationResult result = await downloader.DownloadAsync(
            manifest, temp.Path, allowUnpinned: true);

        Assert.True(result.IsComplete);
        Assert.False(result.Files[0].WasChecked);
    }

    [Fact]
    public async Task AlreadyPresentAndVerifiedFilesAreNotRefetched()
    {
        using var temp = new TempDirectory();
        var handler = new StubHandler(Payload);
        using var http = new HttpClient(handler);
        var downloader = new ModelDownloader(http);

        await downloader.DownloadAsync(ManifestFor(), temp.Path);
        Assert.Equal(1, handler.RequestCount);

        await downloader.DownloadAsync(ManifestFor(), temp.Path);
        Assert.Equal(1, handler.RequestCount);   // resumed, not re-downloaded
    }

    [Fact]
    public async Task CorruptExistingFilesAreReplaced()
    {
        using var temp = new TempDirectory();
        Directory.CreateDirectory(Path.Combine(temp.Path, "unet"));
        await File.WriteAllTextAsync(Path.Combine(temp.Path, "unet", "model.onnx"), "junk");

        var handler = new StubHandler(Payload);
        using var http = new HttpClient(handler);

        ModelVerificationResult result = await new ModelDownloader(http)
            .DownloadAsync(ManifestFor(), temp.Path);

        Assert.True(result.IsComplete);
        Assert.Equal(1, handler.RequestCount);
        Assert.Equal(Payload, await File.ReadAllBytesAsync(Path.Combine(temp.Path, "unet", "model.onnx")));
    }

    [Fact]
    public async Task HttpFailuresAreReportedWithTheFileName()
    {
        using var temp = new TempDirectory();
        using var http = new HttpClient(new StubHandler(Payload, HttpStatusCode.NotFound));

        ModelDownloadException error = await Assert.ThrowsAsync<ModelDownloadException>(() =>
            new ModelDownloader(http).DownloadAsync(ManifestFor(), temp.Path));

        Assert.Contains("unet/model.onnx", error.Message, StringComparison.Ordinal);
        Assert.Contains("404", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task ProgressIsReportedThroughToCompletion()
    {
        using var temp = new TempDirectory();
        using var http = new HttpClient(new StubHandler(Payload));
        var reports = new List<ModelDownloadProgress>();

        await new ModelDownloader(http).DownloadAsync(
            ManifestFor(), temp.Path, new SynchronousProgress<ModelDownloadProgress>(reports.Add));

        Assert.NotEmpty(reports);
        Assert.Contains(reports, r => r.Stage == "Downloading");
        Assert.Contains(reports, r => r.Stage == "Verifying");
        Assert.Equal(1d, reports[^1].Fraction, 3);
    }

    [Fact]
    public async Task CancellationStopsTheDownload()
    {
        using var temp = new TempDirectory();
        using var cts = new CancellationTokenSource();
        using var http = new HttpClient(new StubHandler(Payload, onRequest: cts.Cancel));

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() =>
            new ModelDownloader(http).DownloadAsync(
                ManifestFor(), temp.Path, cancellationToken: cts.Token));
    }

    [Fact]
    public async Task VerifyReportsMissingAndCorruptFilesSeparately()
    {
        using var temp = new TempDirectory();
        var manifest = new ModelManifest("t", "d", [
            new ModelSource("present.onnx", "https://example.com/a", HashOf(Payload), Payload.Length),
            new ModelSource("absent.onnx", "https://example.com/b", HashOf(Payload), Payload.Length),
        ]);
        await File.WriteAllTextAsync(Path.Combine(temp.Path, "present.onnx"), "wrong content");

        ModelVerificationResult result = await new ModelDownloader().VerifyAsync(manifest, temp.Path);

        Assert.False(result.IsComplete);
        Assert.Single(result.Missing);
        Assert.Single(result.Corrupt);
    }

    [Fact]
    public void DestinationsAreConfinedToTheModelFolder()
    {
        using var temp = new TempDirectory();

        Assert.Throws<ModelManifestException>(() =>
            ModelDownloader.ResolveDestination(temp.Path, "../escape.onnx"));

        string safe = ModelDownloader.ResolveDestination(temp.Path, "unet/model.onnx");
        Assert.StartsWith(Path.GetFullPath(temp.Path), safe, StringComparison.Ordinal);
    }

    [Fact]
    public async Task ComputeManifestPinsHashesFromDiskContents()
    {
        using var temp = new TempDirectory();
        Directory.CreateDirectory(Path.Combine(temp.Path, "unet"));
        await File.WriteAllBytesAsync(Path.Combine(temp.Path, "unet", "model.onnx"), Payload);

        var template = new ModelManifest("t", "d", [
            new ModelSource("unet/model.onnx", "https://example.com/unet"),
        ]);

        ModelManifest pinned = await ModelDownloader.ComputeManifestAsync(template, temp.Path);

        Assert.Equal(HashOf(Payload), pinned.Files[0].Sha256);
        Assert.Equal(Payload.Length, pinned.Files[0].SizeBytes);
    }

    [Theory]
    [InlineData(0, "0 B")]
    [InlineData(1536, "1.5 KB")]
    [InlineData(3_650_722_201, "3.4 GB")]
    public void SizesAreFormattedForHumans(long bytes, string expected)
    {
        Assert.Equal(expected, ModelDownloader.FormatBytes(bytes));
    }

    private sealed class StubHandler(
        byte[] payload,
        HttpStatusCode status = HttpStatusCode.OK,
        Action? onRequest = null) : HttpMessageHandler
    {
        private int _requestCount;

        public int RequestCount => Volatile.Read(ref _requestCount);

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Interlocked.Increment(ref _requestCount);
            onRequest?.Invoke();
            cancellationToken.ThrowIfCancellationRequested();

            return Task.FromResult(new HttpResponseMessage(status)
            {
                Content = new ByteArrayContent(payload),
            });
        }
    }

    private sealed class SynchronousProgress<T>(Action<T> handler) : IProgress<T>
    {
        public void Report(T value) => handler(value);
    }
}

public class ModelDirectoryResolverTests
{
    private static void CreateCompleteModelDirectory(string path)
    {
        foreach (Core.Inference.ModelFile file in Core.Inference.ModelLayout.RequiredFiles)
        {
            string full = Path.Combine(path, file.RelativePath.Replace('/', Path.DirectorySeparatorChar));
            Directory.CreateDirectory(Path.GetDirectoryName(full)!);
            File.WriteAllText(full, "x");
        }
    }

    [Fact]
    public void PrefersTheConfiguredDirectoryWhenItIsComplete()
    {
        using var app = new TempDirectory();
        using var local = new TempDirectory();
        using var configured = new TempDirectory();
        CreateCompleteModelDirectory(configured.Path);

        ResolvedModelDirectory resolved = new ModelDirectoryResolver(app.Path, local.Path)
            .Resolve(configured.Path);

        Assert.Equal(ModelDirectorySource.Setting, resolved.Source);
        Assert.True(resolved.IsComplete);
    }

    [Fact]
    public void FallsBackToModelsBundledNextToTheExecutable()
    {
        using var app = new TempDirectory();
        using var local = new TempDirectory();
        CreateCompleteModelDirectory(Path.Combine(app.Path, "models"));

        ResolvedModelDirectory resolved = new ModelDirectoryResolver(app.Path, local.Path).Resolve(null);

        Assert.Equal(ModelDirectorySource.BundledWithInstall, resolved.Source);
        Assert.True(resolved.IsComplete);
    }

    [Fact]
    public void FallsBackToTheDownloadedPerUserCopy()
    {
        using var app = new TempDirectory();
        using var local = new TempDirectory();
        CreateCompleteModelDirectory(Path.Combine(local.Path, "WowIconForge", "models"));

        ResolvedModelDirectory resolved = new ModelDirectoryResolver(app.Path, local.Path).Resolve(null);

        Assert.Equal(ModelDirectorySource.UserData, resolved.Source);
        Assert.True(resolved.IsComplete);
    }

    [Fact]
    public void BundledModelsWinOverAnIncompleteSetting()
    {
        using var app = new TempDirectory();
        using var local = new TempDirectory();
        using var configured = new TempDirectory();   // exists but empty
        CreateCompleteModelDirectory(Path.Combine(app.Path, "models"));

        ResolvedModelDirectory resolved = new ModelDirectoryResolver(app.Path, local.Path)
            .Resolve(configured.Path);

        Assert.Equal(ModelDirectorySource.BundledWithInstall, resolved.Source);
    }

    [Fact]
    public void WithNothingInstalledItPointsAtTheDownloadTarget()
    {
        using var app = new TempDirectory();
        using var local = new TempDirectory();

        var resolver = new ModelDirectoryResolver(app.Path, local.Path);
        ResolvedModelDirectory resolved = resolver.Resolve(null);

        Assert.False(resolved.IsComplete);
        Assert.True(resolver.NeedsFirstRunWizard(null));
        Assert.Equal(resolver.UserDataDirectory, resolved.Path);
        Assert.Contains("WowIconForge", resolved.Path, StringComparison.Ordinal);
    }

    [Fact]
    public void AnIncompleteUserChoiceIsKeptSoTheWizardCanWorkOnIt()
    {
        using var app = new TempDirectory();
        using var local = new TempDirectory();
        using var configured = new TempDirectory();

        ResolvedModelDirectory resolved = new ModelDirectoryResolver(app.Path, local.Path)
            .Resolve(configured.Path);

        Assert.Equal(configured.Path, resolved.Path);
        Assert.False(resolved.IsComplete);
    }

    [Fact]
    public void DownloadTargetIsUnderLocalAppDataNotProgramFiles()
    {
        // Installing per-machine means the app folder needs elevation to write,
        // and the wizard downloads gigabytes.
        using var app = new TempDirectory();
        using var local = new TempDirectory();

        var resolver = new ModelDirectoryResolver(app.Path, local.Path);

        Assert.StartsWith(local.Path, resolver.UserDataDirectory, StringComparison.Ordinal);
        Assert.DoesNotContain(app.Path, resolver.UserDataDirectory, StringComparison.Ordinal);
    }
}
