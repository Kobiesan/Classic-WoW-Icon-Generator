using WowIconForge.Core;
using WowIconForge.Core.Compositing;
using WowIconForge.Core.Imaging;
using WowIconForge.Core.Inference;
using Xunit;

namespace WowIconForge.Core.Tests;

public class PromptBuilderTests
{
    [Theory]
    [InlineData("weapon, sword", "wowicon, weapon, sword")]
    [InlineData("  weapon, sword  ", "wowicon, weapon, sword")]
    [InlineData("", "wowicon")]
    [InlineData(", weapon", "wowicon, weapon")]
    public void TriggerWordIsPrepended(string prompt, string expected)
    {
        Assert.Equal(expected, PromptBuilder.Build(prompt));
    }

    [Theory]
    [InlineData("wowicon, weapon, sword")]
    [InlineData("WowIcon, weapon, sword")]
    [InlineData("  wowicon , weapon")]
    public void ExistingTriggerIsNotDuplicated(string prompt)
    {
        string built = PromptBuilder.Build(prompt);

        Assert.Single(
            built.Split(',', StringSplitOptions.TrimEntries),
            term => term.Equals("wowicon", StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public void TriggerWordIsConfigurable()
    {
        Assert.Equal("myicon, sword", PromptBuilder.Build("sword", "myicon"));
    }

    [Fact]
    public void EmptyTriggerWordLeavesThePromptAlone()
    {
        Assert.Equal("sword", PromptBuilder.Build("sword", ""));
    }

    [Fact]
    public void TriggerOnlyCountsAsTheFirstTerm()
    {
        // "wowicon" appearing later in the prompt is not a leading trigger.
        Assert.Equal("wowicon, sword, wowicon style", PromptBuilder.Build("sword, wowicon style"));
    }
}

public class TriggerWordGeneratorTests
{
    [Fact]
    public async Task WrapsEveryPrompt()
    {
        var inner = new RecordingGenerator();
        var generator = new TriggerWordGenerator(inner);

        await generator.GenerateAsync(new IconRequest { Prompt = "weapon, sword" });

        Assert.Equal("wowicon, weapon, sword", inner.LastRequest?.Prompt);
    }

    [Fact]
    public async Task PicksUpTriggerWordChangesWithoutRebuilding()
    {
        var inner = new RecordingGenerator();
        string trigger = "wowicon";
        var generator = new TriggerWordGenerator(inner, () => trigger);

        await generator.GenerateAsync(new IconRequest { Prompt = "sword" });
        Assert.Equal("wowicon, sword", inner.LastRequest?.Prompt);

        trigger = "myicon";
        await generator.GenerateAsync(new IconRequest { Prompt = "sword" });
        Assert.Equal("myicon, sword", inner.LastRequest?.Prompt);
    }

    [Fact]
    public async Task LeavesEveryOtherFieldAlone()
    {
        var inner = new RecordingGenerator();
        var generator = new TriggerWordGenerator(inner);

        await generator.GenerateAsync(new IconRequest
        {
            Prompt = "sword",
            NegativePrompt = "blurry",
            Seed = 99,
            Steps = 12,
            CfgScale = 6f,
            BatchCount = 3,
        });

        Assert.Equal("blurry", inner.LastRequest?.NegativePrompt);
        Assert.Equal(99, inner.LastRequest?.Seed);
        Assert.Equal(12, inner.LastRequest?.Steps);
        Assert.Equal(3, inner.LastRequest?.BatchCount);
    }

    private sealed class RecordingGenerator : IIconGenerator
    {
        public IconRequest? LastRequest { get; private set; }

        public bool IsReady => true;

        public Task<IReadOnlyList<GeneratedImage>> GenerateAsync(
            IconRequest request,
            IProgress<GenerationProgress>? progress = null,
            CancellationToken cancellationToken = default)
        {
            LastRequest = request;
            return Task.FromResult<IReadOnlyList<GeneratedImage>>([]);
        }
    }
}

public class IconRequestTests
{
    [Fact]
    public void ValidRequestPasses()
    {
        new IconRequest { Prompt = "sword" }.Validate();
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    public void EmptyPromptIsRejected(string prompt)
    {
        Assert.Throws<ArgumentException>(() => new IconRequest { Prompt = prompt }.Validate());
    }

    [Theory]
    [InlineData(0)]
    [InlineData(151)]
    public void OutOfRangeStepsAreRejected(int steps)
    {
        Assert.Throws<ArgumentOutOfRangeException>(() =>
            new IconRequest { Prompt = "sword", Steps = steps }.Validate());
    }

    [Theory]
    [InlineData(0f)]
    [InlineData(31f)]
    public void OutOfRangeCfgIsRejected(float cfg)
    {
        Assert.Throws<ArgumentOutOfRangeException>(() =>
            new IconRequest { Prompt = "sword", CfgScale = cfg }.Validate());
    }

    [Theory]
    [InlineData(0)]
    [InlineData(9)]
    public void OutOfRangeBatchCountIsRejected(int batch)
    {
        Assert.Throws<ArgumentOutOfRangeException>(() =>
            new IconRequest { Prompt = "sword", BatchCount = batch }.Validate());
    }

    [Fact]
    public void BatchSeedsWalkUpwardFromTheBase()
    {
        var request = new IconRequest { Prompt = "sword", Seed = 1000 };

        Assert.Equal(1000, request.SeedFor(0));
        Assert.Equal(1003, request.SeedFor(3));
    }
}

public class GenerationProgressTests
{
    [Fact]
    public void FractionSpansTheWholeBatch()
    {
        Assert.Equal(0d, new GenerationProgress(0, 4, 0, 10, "x").Fraction);
        Assert.Equal(0.25d, new GenerationProgress(1, 4, 0, 10, "x").Fraction, 3);
        Assert.Equal(1d, new GenerationProgress(3, 4, 10, 10, "x").Fraction, 3);
    }

    [Fact]
    public void DegenerateValuesDoNotDivideByZero()
    {
        Assert.Equal(0d, new GenerationProgress(0, 0, 0, 0, "x").Fraction);
    }
}

public class StubIconGeneratorTests
{
    [Fact]
    public async Task ProducesTheRequestedBatchAt512()
    {
        var generator = new StubIconGenerator();

        IReadOnlyList<GeneratedImage> images = await generator.GenerateAsync(
            new IconRequest { Prompt = "wowicon, weapon, sword", BatchCount = 4, Steps = 2 });

        Assert.Equal(4, images.Count);
        Assert.All(images, image =>
        {
            Assert.Equal(512, image.Image.Width);
            Assert.Equal(512, image.Image.Height);
        });
    }

    [Fact]
    public async Task SeedsAreDistinctAndAscending()
    {
        var generator = new StubIconGenerator();

        IReadOnlyList<GeneratedImage> images = await generator.GenerateAsync(
            new IconRequest { Prompt = "sword", Seed = 500, BatchCount = 3, Steps = 1 });

        Assert.Equal([500L, 501L, 502L], images.Select(i => i.Seed));
    }

    [Fact]
    public void SameSeedAndPromptGiveIdenticalPixels()
    {
        // "Regenerate with this seed" depends on this being true.
        RgbaImage first = StubIconGenerator.Render(42, "wowicon, weapon, sword");
        RgbaImage second = StubIconGenerator.Render(42, "wowicon, weapon, sword");

        Assert.Equal(first.Pixels, second.Pixels);
    }

    [Fact]
    public void DifferentSeedsGiveDifferentPixels()
    {
        RgbaImage first = StubIconGenerator.Render(1, "sword");
        RgbaImage second = StubIconGenerator.Render(2, "sword");

        Assert.NotEqual(first.Pixels, second.Pixels);
    }

    [Fact]
    public async Task ReportsProgressForEveryStepOfEveryImage()
    {
        var reports = new List<GenerationProgress>();
        var progress = new Progress<GenerationProgress>(reports.Add);
        var generator = new StubIconGenerator();

        // Progress<T> posts asynchronously, so collect through a TaskCompletionSource-free
        // synchronous sink instead to keep the assertion deterministic.
        var sink = new SynchronousProgress(reports);
        await generator.GenerateAsync(
            new IconRequest { Prompt = "sword", BatchCount = 2, Steps = 5 }, sink);

        Assert.Equal(12, reports.Count);     // 2 images x (5 steps + 1 decode)
        Assert.Contains(reports, r => r.Stage.Contains("Denoising", StringComparison.Ordinal));
        Assert.Contains(reports, r => r.Stage.Contains("Decoding", StringComparison.Ordinal));
        _ = progress;
    }

    [Fact]
    public async Task CancellationIsHonoured()
    {
        using var cts = new CancellationTokenSource();
        var generator = new StubIconGenerator(TimeSpan.FromMilliseconds(5));

        Task task = generator.GenerateAsync(
            new IconRequest { Prompt = "sword", BatchCount = 8, Steps = 50 },
            progress: null,
            cancellationToken: cts.Token);

        cts.Cancel();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => task);
    }

    [Fact]
    public async Task InvalidRequestsAreRejectedBeforeAnyWork()
    {
        var generator = new StubIconGenerator();

        await Assert.ThrowsAsync<ArgumentException>(() =>
            generator.GenerateAsync(new IconRequest { Prompt = "" }));
    }

    [Fact]
    public void IsAlwaysReady()
    {
        Assert.True(new StubIconGenerator().IsReady);
    }

    private sealed class SynchronousProgress(List<GenerationProgress> sink) : IProgress<GenerationProgress>
    {
        public void Report(GenerationProgress value) => sink.Add(value);
    }
}

public class IconForgePipelineTests
{
    [Fact]
    public async Task GeneratesAndCompositesInOneCall()
    {
        var pipeline = new IconForgePipeline(new StubIconGenerator());

        IReadOnlyList<IconResult> results = await pipeline.GenerateAsync(
            new IconRequest { Prompt = "wowicon, weapon, sword", BatchCount = 2, Steps = 2 },
            TestImages.BorderTemplate());

        Assert.Equal(2, results.Count);
        Assert.All(results, result =>
        {
            Assert.Equal(64, result.Icon.Width);
            Assert.Equal(512, result.SourceArt.Width);
            Assert.Equal(0, result.Icon.GetPixel(0, 0).A);       // corners still transparent
        });
    }

    [Fact]
    public async Task RecompositeReusesArtWithoutRegenerating()
    {
        var pipeline = new IconForgePipeline(new StubIconGenerator());
        IReadOnlyList<IconResult> results = await pipeline.GenerateAsync(
            new IconRequest { Prompt = "sword", Steps = 1 }, TestImages.BorderTemplate());

        IconResult sharpened = pipeline.Recomposite(
            results[0], TestImages.BorderTemplate(), new CompositeOptions { SharpenAmount = 2f });

        Assert.Same(results[0].SourceArt, sharpened.SourceArt);
        Assert.Equal(results[0].Seed, sharpened.Seed);
        Assert.False(results[0].Icon.Pixels.SequenceEqual(sharpened.Icon.Pixels));
    }
}
