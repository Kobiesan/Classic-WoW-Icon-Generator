using WowIconForge.Core.Imaging;

namespace WowIconForge.Core.Inference;

/// <summary>One generation request from the UI.</summary>
public sealed record IconRequest
{
    public const int DefaultSteps = 24;
    public const float DefaultCfgScale = 7.5f;
    public const int MaxBatchCount = 8;

    public required string Prompt { get; init; }

    public string NegativePrompt { get; init; } = string.Empty;

    /// <summary>Seed of the first image; a batch walks upward from here.</summary>
    public long Seed { get; init; }

    public int Steps { get; init; } = DefaultSteps;

    public float CfgScale { get; init; } = DefaultCfgScale;

    /// <summary>How many icons to produce. The results grid holds eight.</summary>
    public int BatchCount { get; init; } = 1;

    /// <summary>Throws if any field is outside what the pipeline can honour.</summary>
    public void Validate()
    {
        if (string.IsNullOrWhiteSpace(Prompt))
        {
            throw new ArgumentException("Prompt must not be empty.", nameof(Prompt));
        }

        if (Steps is < 1 or > 150)
        {
            throw new ArgumentOutOfRangeException(nameof(Steps), Steps, "Steps must be within [1, 150].");
        }

        if (float.IsNaN(CfgScale) || CfgScale is < 1f or > 30f)
        {
            throw new ArgumentOutOfRangeException(nameof(CfgScale), CfgScale, "CFG must be within [1, 30].");
        }

        if (BatchCount is < 1 or > MaxBatchCount)
        {
            throw new ArgumentOutOfRangeException(
                nameof(BatchCount), BatchCount, $"Batch count must be within [1, {MaxBatchCount}].");
        }
    }

    /// <summary>The seed used for image <paramref name="index"/> of the batch.</summary>
    public long SeedFor(int index) => unchecked(Seed + index);
}

/// <summary>Raw art straight out of the model, before compositing.</summary>
public sealed class GeneratedImage
{
    public required RgbaImage Image { get; init; }

    /// <summary>The exact seed this image came from, so "regenerate with this seed" works.</summary>
    public required long Seed { get; init; }

    /// <summary>The prompt actually sent to the model, trigger word included.</summary>
    public required string ResolvedPrompt { get; init; }

    public string ResolvedNegativePrompt { get; init; } = string.Empty;
}

/// <summary>Progress for a single denoising step, reported through <see cref="IProgress{T}"/>.</summary>
public sealed record GenerationProgress(
    int ImageIndex,
    int BatchCount,
    int Step,
    int TotalSteps,
    string Stage)
{
    /// <summary>Overall completion across the whole batch, in [0, 1].</summary>
    public double Fraction
    {
        get
        {
            if (BatchCount <= 0 || TotalSteps <= 0)
            {
                return 0d;
            }

            double perImage = 1d / BatchCount;
            double withinImage = Math.Clamp((double)Step / TotalSteps, 0d, 1d);
            return Math.Clamp((ImageIndex * perImage) + (withinImage * perImage), 0d, 1d);
        }
    }

    public override string ToString() =>
        $"{Stage} - image {ImageIndex + 1}/{BatchCount}, step {Step}/{TotalSteps}";
}

/// <summary>
/// Produces 512x512 art from a prompt. Implementations must be cancellable and
/// must never touch the UI thread.
/// </summary>
public interface IIconGenerator
{
    /// <summary>True when the backing models are present and the generator can run.</summary>
    bool IsReady { get; }

    Task<IReadOnlyList<GeneratedImage>> GenerateAsync(
        IconRequest request,
        IProgress<GenerationProgress>? progress = null,
        CancellationToken cancellationToken = default);
}
