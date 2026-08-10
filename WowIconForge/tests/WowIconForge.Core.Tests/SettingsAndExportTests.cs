using WowIconForge.Core.Blp;
using WowIconForge.Core.Compositing;
using WowIconForge.Core.Export;
using WowIconForge.Core.Imaging;
using WowIconForge.Core.Inference;
using WowIconForge.Core.Settings;
using Xunit;

namespace WowIconForge.Core.Tests;

public class ModelLayoutTests
{
    [Fact]
    public void MissingDirectoryNeedsTheWizard()
    {
        ModelDirectoryStatus status = ModelLayout.Probe(Path.Combine(Path.GetTempPath(), "no-such-dir-xyz"));

        Assert.False(status.DirectoryExists);
        Assert.False(status.IsComplete);
        Assert.True(status.NeedsFirstRunWizard);
    }

    [Fact]
    public void UnsetDirectoryNeedsTheWizard()
    {
        Assert.True(ModelLayout.Probe(null).NeedsFirstRunWizard);
        Assert.True(ModelLayout.Probe("").NeedsFirstRunWizard);
    }

    [Fact]
    public void EmptyDirectoryNeedsTheWizard()
    {
        using var temp = new TempDirectory();

        ModelDirectoryStatus status = ModelLayout.Probe(temp.Path);

        Assert.True(status.DirectoryExists);
        Assert.True(status.IsEmpty);
        Assert.True(status.NeedsFirstRunWizard);
    }

    [Fact]
    public void CompleteDirectoryIsAccepted()
    {
        using var temp = new TempDirectory();
        foreach (ModelFile file in ModelLayout.RequiredFiles)
        {
            temp.CreateFile(file.RelativePath);
        }

        ModelDirectoryStatus status = ModelLayout.Probe(temp.Path);

        Assert.True(status.IsComplete);
        Assert.False(status.NeedsFirstRunWizard);
        Assert.Empty(status.Missing);
    }

    [Fact]
    public void OptionalFilesAreNotRequired()
    {
        using var temp = new TempDirectory();
        foreach (ModelFile file in ModelLayout.RequiredFiles)
        {
            temp.CreateFile(file.RelativePath);
        }

        // vae_encoder is only needed for image-to-image and is deliberately absent.
        Assert.True(ModelLayout.Probe(temp.Path).IsComplete);
        Assert.Contains(ModelLayout.Files, f => !f.Required);
    }

    [Fact]
    public void PartialDirectoryListsWhatIsMissing()
    {
        using var temp = new TempDirectory();
        temp.CreateFile("unet/model.onnx");

        ModelDirectoryStatus status = ModelLayout.Probe(temp.Path);

        Assert.False(status.IsComplete);
        Assert.False(status.NeedsFirstRunWizard);   // something recognisable is there
        Assert.Contains(status.Missing, f => f.RelativePath == "vae_decoder/model.onnx");
        Assert.Contains(status.Present, f => f.RelativePath == "unet/model.onnx");
    }

    [Fact]
    public void UserMessageNamesTheMissingFilesWithoutJargon()
    {
        using var temp = new TempDirectory();
        temp.CreateFile("unet/model.onnx");

        string message = ModelLayout.Probe(temp.Path).ToUserMessage();

        Assert.Contains("vae_decoder/model.onnx", message, StringComparison.Ordinal);
        Assert.Contains("Copy the missing files", message, StringComparison.Ordinal);
    }

    [Fact]
    public void UserMessageForAnEmptyFolderExplainsWhatToDo()
    {
        using var temp = new TempDirectory();

        string message = ModelLayout.Probe(temp.Path).ToUserMessage();

        Assert.Contains("is empty", message, StringComparison.Ordinal);
    }
}

public class ExecutionProviderSelectorTests
{
    [Fact]
    public void PrefersDirectMlWhenAvailable()
    {
        var selector = new ExecutionProviderSelector(() => true);

        ExecutionProviderPlan plan = selector.Select();

        Assert.Equal(ExecutionProviderKind.DirectML, plan.Provider);
        Assert.False(plan.IsFallback);
    }

    [Fact]
    public void FallsBackToCpuWhenUnavailable()
    {
        var selector = new ExecutionProviderSelector(() => false);

        ExecutionProviderPlan plan = selector.Select();

        Assert.Equal(ExecutionProviderKind.Cpu, plan.Provider);
        Assert.True(plan.IsFallback);
        Assert.Contains("No DirectML", plan.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void ForceCpuOverridesAnAvailableGpu()
    {
        var selector = new ExecutionProviderSelector(() => true);

        Assert.Equal(ExecutionProviderKind.Cpu, selector.Select(forceCpu: true).Provider);
    }

    [Fact]
    public void AThrowingProbeFallsBackRatherThanCrashing()
    {
        var selector = new ExecutionProviderSelector(() => throw new InvalidOperationException("no driver"));

        ExecutionProviderPlan plan = selector.Select();

        Assert.Equal(ExecutionProviderKind.Cpu, plan.Provider);
        Assert.Contains("check failed", plan.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void DeviceIdIsCarriedThrough()
    {
        var selector = new ExecutionProviderSelector(() => true);

        Assert.Equal(1, selector.Select(deviceId: 1).DeviceId);
    }

    [Fact]
    public void NegativeDeviceIdIsRejected()
    {
        var selector = new ExecutionProviderSelector(() => true);

        Assert.Throws<ArgumentOutOfRangeException>(() => selector.Select(deviceId: -1));
    }
}

public class IconExporterTests
{
    [Theory]
    [InlineData("icon.png", IconFormat.Png)]
    [InlineData("icon.blp", IconFormat.Blp)]
    [InlineData("icon.BLP", IconFormat.Blp)]
    [InlineData("icon", IconFormat.Png)]
    public void FormatIsChosenByExtension(string path, IconFormat expected)
    {
        Assert.Equal(expected, IconExporter.FormatFor(path));
    }

    [Fact]
    public void PngBytesAreAValidPng()
    {
        byte[] bytes = new IconExporter().ToBytes(TestImages.FewColours(), IconFormat.Png);

        Assert.Equal([0x89, 0x50, 0x4E, 0x47], bytes.Take(4));
    }

    [Fact]
    public void BlpBytesAreAValidBlp2()
    {
        byte[] bytes = new IconExporter().ToBytes(TestImages.FewColours(), IconFormat.Blp);

        Assert.Equal(2, BlpReader.ReadHeader(bytes).Version);
    }

    [Fact]
    public void PngRoundTripsThroughDisk()
    {
        using var temp = new TempDirectory();
        string path = Path.Combine(temp.Path, "nested", "icon.png");
        var compositor = new IconCompositor();
        RgbaImage icon = compositor.Composite(
            TestImages.Gradient(512), TestImages.BorderTemplate(), new CompositeOptions { SharpenAmount = 0f });

        new IconExporter().Save(icon, path);

        Assert.True(File.Exists(path));
        using var reloaded = SixLabors.ImageSharp.Image.Load<SixLabors.ImageSharp.PixelFormats.Rgba32>(path);
        Assert.Equal(64, reloaded.Width);
        Assert.Equal(0, reloaded[0, 0].A);   // transparent corner survives the PNG
    }

    [Fact]
    public void BlpRoundTripsThroughDisk()
    {
        using var temp = new TempDirectory();
        string path = Path.Combine(temp.Path, "icon.blp");

        new IconExporter().Save(TestImages.FewColours(), path);

        Assert.Equal(TestImages.FewColours().Pixels, BlpReader.Load(path).Pixels);
    }

    [Theory]
    [InlineData("wowicon, weapon, sword", 42, IconFormat.Png, "wowicon_weapon_sword_42.png")]
    [InlineData("wowicon, weapon, sword", 42, IconFormat.Blp, "wowicon_weapon_sword_42.blp")]
    [InlineData("", 7, IconFormat.Png, "icon_7.png")]
    [InlineData("!!!", 7, IconFormat.Png, "icon_7.png")]
    public void SuggestedFileNamesAreSafe(string prompt, long seed, IconFormat format, string expected)
    {
        Assert.Equal(expected, IconExporter.SuggestFileName(prompt, seed, format));
    }

    [Fact]
    public void SuggestedFileNamesAreLengthCapped()
    {
        string name = IconExporter.SuggestFileName(new string('a', 200), 1, IconFormat.Png);

        Assert.True(name.Length < 64, $"name was {name.Length} characters");
    }
}

public class IconForgeSettingsTests
{
    [Fact]
    public void DefaultsAreUsable()
    {
        var settings = new IconForgeSettings();

        Assert.Equal("wowicon", settings.TriggerWord);
        Assert.Equal(UnsharpMask.DefaultAmount, settings.SharpenAmount);
        Assert.False(settings.HasModelDirectory);
    }

    [Fact]
    public void RoundTripsThroughDisk()
    {
        using var temp = new TempDirectory();
        string path = Path.Combine(temp.Path, "settings.json");
        var settings = new IconForgeSettings
        {
            ModelDirectory = @"C:\models",
            TemplatePath = @"C:\border.png",
            OutputDirectory = @"C:\out",
            SharpenAmount = 0.8f,
            TriggerWord = "myicon",
            ForceCpu = true,
        };

        settings.Save(path);

        Assert.Equal(settings, IconForgeSettings.Load(path));
    }

    [Fact]
    public void MissingFileYieldsDefaults()
    {
        using var temp = new TempDirectory();

        IconForgeSettings loaded = IconForgeSettings.Load(Path.Combine(temp.Path, "absent.json"));

        Assert.Equal(new IconForgeSettings(), loaded);
    }

    [Fact]
    public void CorruptFileDoesNotStopTheAppStarting()
    {
        using var temp = new TempDirectory();
        string path = Path.Combine(temp.Path, "settings.json");
        File.WriteAllText(path, "{ this is not json");

        Assert.Equal(new IconForgeSettings(), IconForgeSettings.Load(path));
    }

    [Fact]
    public void NormalizedClampsHandEditedValues()
    {
        var settings = new IconForgeSettings
        {
            SharpenAmount = 99f,
            SharpenSigma = -1f,
            TriggerWord = "   ",
        }.Normalized();

        Assert.Equal(UnsharpMask.MaxAmount, settings.SharpenAmount);
        Assert.Equal(UnsharpMask.DefaultSigma, settings.SharpenSigma);
        Assert.Equal("wowicon", settings.TriggerWord);
    }
}

/// <summary>A temp directory that cleans itself up.</summary>
internal sealed class TempDirectory : IDisposable
{
    public TempDirectory()
    {
        Path = System.IO.Path.Combine(System.IO.Path.GetTempPath(), $"wowiconforge_{Guid.NewGuid():N}");
        Directory.CreateDirectory(Path);
    }

    public string Path { get; }

    public string CreateFile(string relativePath, string content = "x")
    {
        string full = System.IO.Path.Combine(
            Path, relativePath.Replace('/', System.IO.Path.DirectorySeparatorChar));
        Directory.CreateDirectory(System.IO.Path.GetDirectoryName(full)!);
        File.WriteAllText(full, content);
        return full;
    }

    public void Dispose()
    {
        try
        {
            Directory.Delete(Path, recursive: true);
        }
        catch (IOException)
        {
            // Best effort; a leftover temp directory is not worth failing a test.
        }
    }
}
