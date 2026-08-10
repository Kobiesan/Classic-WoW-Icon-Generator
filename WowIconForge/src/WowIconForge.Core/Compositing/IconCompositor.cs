using SixLabors.ImageSharp;
using SixLabors.ImageSharp.PixelFormats;
using SixLabors.ImageSharp.Processing;
using WowIconForge.Core.Imaging;

namespace WowIconForge.Core.Compositing;

/// <summary>Knobs for a single compositing pass.</summary>
public sealed record CompositeOptions
{
    public static readonly CompositeOptions Default = new();

    /// <summary>Unsharp strength applied after the downscale. Zero disables it.</summary>
    public float SharpenAmount { get; init; } = UnsharpMask.DefaultAmount;

    /// <summary>Blur radius the unsharp mask subtracts against.</summary>
    public float SharpenSigma { get; init; } = UnsharpMask.DefaultSigma;

    /// <summary>Template alpha at or above this blocks the flood fill and counts as border.</summary>
    public byte OpaqueThreshold { get; init; } = ContentMask.DefaultOpaqueThreshold;
}

public interface IIconCompositor
{
    /// <summary>Fits generated art into a border template and returns the finished icon.</summary>
    RgbaImage Composite(RgbaImage generated, BorderTemplate template, CompositeOptions? options = null);
}

/// <summary>
/// Puts generated art behind a border template, in the exact order the pipeline
/// requires.
/// </summary>
/// <remarks>
/// <list type="number">
/// <item>Load the border template (the caller supplies it, already loaded).</item>
/// <item>Derive the content mask once per template (cached).</item>
/// <item>Downscale the art to the template's size with Lanczos, then optionally
/// unsharp it.</item>
/// <item>Zero the alpha of every art pixel outside the content mask.</item>
/// <item>Alpha-composite the template over the masked art.</item>
/// </list>
/// Step order is not incidental. Masking before compositing is what leaves the
/// corners fully transparent: they are outside the mask, so the art there is
/// zeroed, and the template contributes nothing over them.
/// </remarks>
public sealed class IconCompositor : IIconCompositor
{
    private readonly IContentMaskCache _maskCache;

    public IconCompositor()
        : this(new ContentMaskCache())
    {
    }

    public IconCompositor(IContentMaskCache maskCache)
    {
        ArgumentNullException.ThrowIfNull(maskCache);
        _maskCache = maskCache;
    }

    public RgbaImage Composite(RgbaImage generated, BorderTemplate template, CompositeOptions? options = null)
    {
        ArgumentNullException.ThrowIfNull(generated);
        ArgumentNullException.ThrowIfNull(template);
        options ??= CompositeOptions.Default;

        // Step 2: the mask is a pure function of the template, so it is derived
        // once and reused across every icon in the batch.
        ContentMask mask = _maskCache.GetOrDerive(template);

        // Step 3: downscale to the template's size, then sharpen.
        RgbaImage art = Resize(generated, template.Width, template.Height);
        if (options.SharpenAmount > 0f)
        {
            art = UnsharpMask.Apply(art, options.SharpenAmount, options.SharpenSigma);
        }

        // Step 4: anything outside the content mask loses its alpha entirely.
        ApplyMask(art, mask);

        // Step 5: border over art.
        return AlphaCompositeOver(template.Image, art);
    }

    /// <summary>Lanczos resample. Returns a copy even when the size already matches.</summary>
    internal static RgbaImage Resize(RgbaImage source, int width, int height)
    {
        if (source.Width == width && source.Height == height)
        {
            return source.Clone();
        }

        using Image<Rgba32> image = source.ToImageSharp();
        image.Mutate(context => context.Resize(new ResizeOptions
        {
            Size = new Size(width, height),
            Sampler = KnownResamplers.Lanczos3,
            Mode = ResizeMode.Stretch,
        }));

        return image.ToRgbaImage();
    }

    /// <summary>Step 4: zero alpha outside the mask, in place.</summary>
    internal static void ApplyMask(RgbaImage art, ContentMask mask)
    {
        if (art.Width != mask.Width || art.Height != mask.Height)
        {
            throw new ArgumentException(
                $"Art is {art.Width}x{art.Height} but the mask is {mask.Width}x{mask.Height}.",
                nameof(art));
        }

        for (int y = 0; y < art.Height; y++)
        {
            for (int x = 0; x < art.Width; x++)
            {
                if (!mask.Includes(x, y))
                {
                    art.Pixels[(((y * art.Width) + x) * RgbaImage.BytesPerPixel) + 3] = 0;
                }
            }
        }
    }

    /// <summary>
    /// Step 5: standard non-premultiplied source-over of <paramref name="top"/>
    /// onto <paramref name="bottom"/>.
    /// </summary>
    internal static RgbaImage AlphaCompositeOver(RgbaImage top, RgbaImage bottom)
    {
        if (top.Width != bottom.Width || top.Height != bottom.Height)
        {
            throw new ArgumentException(
                $"Cannot composite {top.Width}x{top.Height} over {bottom.Width}x{bottom.Height}.",
                nameof(top));
        }

        var result = new RgbaImage(top.Width, top.Height);

        for (int i = 0; i < result.Pixels.Length; i += RgbaImage.BytesPerPixel)
        {
            float topAlpha = top.Pixels[i + 3] / 255f;
            float bottomAlpha = bottom.Pixels[i + 3] / 255f;
            float outAlpha = topAlpha + (bottomAlpha * (1f - topAlpha));

            if (outAlpha <= 0f)
            {
                // Fully transparent: leave the colour channels at zero so the
                // output is unambiguous rather than carrying stale colour.
                continue;
            }

            for (int channel = 0; channel < 3; channel++)
            {
                float value =
                    ((top.Pixels[i + channel] * topAlpha) +
                     (bottom.Pixels[i + channel] * bottomAlpha * (1f - topAlpha))) / outAlpha;
                result.Pixels[i + channel] = ClampToByte(value);
            }

            result.Pixels[i + 3] = ClampToByte(outAlpha * 255f);
        }

        return result;
    }

    private static byte ClampToByte(float value) =>
        value <= 0f ? (byte)0 : value >= 255f ? (byte)255 : (byte)(value + 0.5f);
}
