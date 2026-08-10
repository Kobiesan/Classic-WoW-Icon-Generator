using WowIconForge.Core.Imaging;

namespace WowIconForge.Core.Inference;

/// <summary>
/// A deterministic stand-in for the real model, so compositing, BLP export and
/// the whole UI can be built and tested before any ONNX file exists.
/// </summary>
/// <remarks>
/// Produces a seeded 512x512 "blob on a background" that is obviously not real
/// art but has the properties the rest of the pipeline cares about: the right
/// size, full alpha coverage in the middle, varied colour, and identical output
/// for identical seeds. It also reports progress per step and honours
/// cancellation, so the UI's progress bar and cancel button can be exercised
/// for real.
/// </remarks>
public sealed class StubIconGenerator : IIconGenerator
{
    public const int OutputSize = 512;

    private readonly TimeSpan _delayPerStep;

    /// <param name="delayPerStep">
    /// Simulated work per denoising step. Zero in tests; a few milliseconds in
    /// the app makes the progress bar and cancel button behave realistically.
    /// </param>
    public StubIconGenerator(TimeSpan? delayPerStep = null)
    {
        _delayPerStep = delayPerStep ?? TimeSpan.Zero;
    }

    /// <summary>Always true: the stub needs nothing on disk.</summary>
    public bool IsReady => true;

    public async Task<IReadOnlyList<GeneratedImage>> GenerateAsync(
        IconRequest request,
        IProgress<GenerationProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);
        request.Validate();

        var results = new List<GeneratedImage>(request.BatchCount);

        for (int index = 0; index < request.BatchCount; index++)
        {
            long seed = request.SeedFor(index);

            for (int step = 1; step <= request.Steps; step++)
            {
                cancellationToken.ThrowIfCancellationRequested();

                if (_delayPerStep > TimeSpan.Zero)
                {
                    await Task.Delay(_delayPerStep, cancellationToken).ConfigureAwait(false);
                }

                progress?.Report(new GenerationProgress(
                    index, request.BatchCount, step, request.Steps, "Denoising (stub)"));
            }

            cancellationToken.ThrowIfCancellationRequested();

            results.Add(new GeneratedImage
            {
                Image = Render(seed, request.Prompt),
                Seed = seed,
                ResolvedPrompt = request.Prompt,
                ResolvedNegativePrompt = request.NegativePrompt,
            });

            progress?.Report(new GenerationProgress(
                index, request.BatchCount, request.Steps, request.Steps, "Decoding (stub)"));
        }

        return results;
    }

    /// <summary>Deterministic placeholder art: identical seed and prompt give identical pixels.</summary>
    public static RgbaImage Render(long seed, string prompt, int size = OutputSize)
    {
        var random = new Random(HashSeed(seed, prompt));

        var background = new RgbaColor(
            (byte)random.Next(20, 70), (byte)random.Next(20, 70), (byte)random.Next(25, 80), 255);
        var foreground = new RgbaColor(
            (byte)random.Next(90, 256), (byte)random.Next(90, 256), (byte)random.Next(90, 256), 255);

        var image = new RgbaImage(size, size);
        image.Fill(background);

        double centreX = size / 2d;
        double centreY = size / 2d;
        double radius = size * (0.22 + (random.NextDouble() * 0.16));
        double lobes = random.Next(3, 8);
        double phase = random.NextDouble() * Math.Tau;

        for (int y = 0; y < size; y++)
        {
            for (int x = 0; x < size; x++)
            {
                double dx = x - centreX;
                double dy = y - centreY;
                double distance = Math.Sqrt((dx * dx) + (dy * dy));
                double angle = Math.Atan2(dy, dx);
                double edge = radius * (1d + (0.18 * Math.Sin((lobes * angle) + phase)));

                if (distance > edge)
                {
                    continue;
                }

                // Fake a top-left light source, the way real icon art is lit.
                double shade = Math.Clamp(1.15 - (distance / edge) - ((dx + dy) / (size * 1.5)), 0.15, 1.35);
                image.SetPixel(x, y, new RgbaColor(
                    Scale(foreground.R, shade), Scale(foreground.G, shade), Scale(foreground.B, shade), 255));
            }
        }

        return image;
    }

    private static byte Scale(byte value, double factor) =>
        (byte)Math.Clamp((int)((value * factor) + 0.5), 0, 255);

    /// <summary>Folds the seed and prompt into one deterministic 32-bit value.</summary>
    private static int HashSeed(long seed, string? prompt)
    {
        unchecked
        {
            int hash = (int)(seed ^ (seed >> 32));
            foreach (char c in prompt ?? string.Empty)
            {
                hash = (hash * 31) + c;
            }

            return hash;
        }
    }
}
