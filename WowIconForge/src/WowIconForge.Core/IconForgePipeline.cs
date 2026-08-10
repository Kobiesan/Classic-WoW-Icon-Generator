using WowIconForge.Core.Compositing;
using WowIconForge.Core.Imaging;
using WowIconForge.Core.Inference;

namespace WowIconForge.Core;

/// <summary>A finished icon: the composited result plus what produced it.</summary>
public sealed class IconResult
{
    public required RgbaImage Icon { get; init; }

    /// <summary>The 512x512 art before downscaling and masking, kept for re-compositing.</summary>
    public required RgbaImage SourceArt { get; init; }

    public required long Seed { get; init; }

    public required string ResolvedPrompt { get; init; }

    public string ResolvedNegativePrompt { get; init; } = string.Empty;
}

/// <summary>
/// Generate, then composite: the single call the UI makes for a batch.
/// </summary>
/// <remarks>
/// Keeping this in Core means the view model owns no pipeline logic, and the
/// whole path from request to finished 64x64 icon is testable against the stub
/// generator with no UI and no model files.
/// </remarks>
public sealed class IconForgePipeline
{
    private readonly IIconGenerator _generator;
    private readonly IIconCompositor _compositor;

    public IconForgePipeline(IIconGenerator generator, IIconCompositor? compositor = null)
    {
        ArgumentNullException.ThrowIfNull(generator);

        _generator = generator;
        _compositor = compositor ?? new IconCompositor();
    }

    public async Task<IReadOnlyList<IconResult>> GenerateAsync(
        IconRequest request,
        BorderTemplate template,
        CompositeOptions? compositeOptions = null,
        IProgress<GenerationProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);
        ArgumentNullException.ThrowIfNull(template);

        IReadOnlyList<GeneratedImage> generated = await _generator
            .GenerateAsync(request, progress, cancellationToken)
            .ConfigureAwait(false);

        var results = new List<IconResult>(generated.Count);

        for (int i = 0; i < generated.Count; i++)
        {
            cancellationToken.ThrowIfCancellationRequested();

            GeneratedImage image = generated[i];
            progress?.Report(new GenerationProgress(
                i, generated.Count, request.Steps, request.Steps, "Compositing"));

            results.Add(new IconResult
            {
                Icon = _compositor.Composite(image.Image, template, compositeOptions),
                SourceArt = image.Image,
                Seed = image.Seed,
                ResolvedPrompt = image.ResolvedPrompt,
                ResolvedNegativePrompt = image.ResolvedNegativePrompt,
            });
        }

        return results;
    }

    /// <summary>
    /// Re-composites art that was already generated, for when the user drags the
    /// sharpening slider or swaps the template. No inference involved.
    /// </summary>
    public IconResult Recomposite(
        IconResult existing, BorderTemplate template, CompositeOptions? compositeOptions = null)
    {
        ArgumentNullException.ThrowIfNull(existing);
        ArgumentNullException.ThrowIfNull(template);

        return new IconResult
        {
            Icon = _compositor.Composite(existing.SourceArt, template, compositeOptions),
            SourceArt = existing.SourceArt,
            Seed = existing.Seed,
            ResolvedPrompt = existing.ResolvedPrompt,
            ResolvedNegativePrompt = existing.ResolvedNegativePrompt,
        };
    }
}
