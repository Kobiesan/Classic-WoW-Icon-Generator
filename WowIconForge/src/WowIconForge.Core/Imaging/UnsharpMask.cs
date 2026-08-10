namespace WowIconForge.Core.Imaging;

/// <summary>
/// A real unsharp mask: <c>result = source + amount * (source - blur(source))</c>.
/// </summary>
/// <remarks>
/// Written out by hand rather than reusing a library sharpen so that "strength"
/// means amount, not blur radius. Downscaling 512px art to 64px softens edges,
/// and a light pass here restores the crispness icons need - but it clips and
/// haloes quickly at these sizes, hence the low default.
/// <para>
/// Only the colour channels are touched. Sharpening alpha would eat into the
/// content mask's edges, which the compositor depends on being exact.
/// </para>
/// </remarks>
public static class UnsharpMask
{
    /// <summary>A gentle default that survives a 8x downscale without haloing.</summary>
    public const float DefaultAmount = 0.35f;

    public const float DefaultSigma = 1.0f;

    /// <summary>Amounts above this are refused as almost certainly a mistake.</summary>
    public const float MaxAmount = 5.0f;

    /// <summary>
    /// Returns a sharpened copy. An <paramref name="amount"/> of zero returns an
    /// untouched clone, which is the "sharpening off" path.
    /// </summary>
    public static RgbaImage Apply(RgbaImage source, float amount, float sigma = DefaultSigma)
    {
        ArgumentNullException.ThrowIfNull(source);

        if (float.IsNaN(amount) || amount < 0f || amount > MaxAmount)
        {
            throw new ArgumentOutOfRangeException(
                nameof(amount), amount, $"Amount must be within [0, {MaxAmount}].");
        }

        if (amount == 0f)
        {
            return source.Clone();
        }

        if (float.IsNaN(sigma) || sigma <= 0f)
        {
            throw new ArgumentOutOfRangeException(nameof(sigma), sigma, "Sigma must be positive.");
        }

        float[] blurred = BlurRgb(source, sigma);
        var result = source.Clone();

        for (int i = 0; i < source.PixelCount; i++)
        {
            int p = i * RgbaImage.BytesPerPixel;
            for (int channel = 0; channel < 3; channel++)
            {
                float original = source.Pixels[p + channel];
                float detail = original - blurred[(i * 3) + channel];
                result.Pixels[p + channel] = ClampToByte(original + (amount * detail));
            }
        }

        return result;
    }

    /// <summary>Separable Gaussian blur over the RGB channels, edges clamped.</summary>
    private static float[] BlurRgb(RgbaImage source, float sigma)
    {
        float[] kernel = BuildKernel(sigma);
        int radius = (kernel.Length - 1) / 2;
        int width = source.Width;
        int height = source.Height;

        var horizontal = new float[source.PixelCount * 3];
        var vertical = new float[source.PixelCount * 3];

        for (int y = 0; y < height; y++)
        {
            for (int x = 0; x < width; x++)
            {
                float r = 0f, g = 0f, b = 0f;
                for (int k = -radius; k <= radius; k++)
                {
                    int sampleX = Math.Clamp(x + k, 0, width - 1);
                    int offset = ((y * width) + sampleX) * RgbaImage.BytesPerPixel;
                    float weight = kernel[k + radius];
                    r += source.Pixels[offset] * weight;
                    g += source.Pixels[offset + 1] * weight;
                    b += source.Pixels[offset + 2] * weight;
                }

                int target = ((y * width) + x) * 3;
                horizontal[target] = r;
                horizontal[target + 1] = g;
                horizontal[target + 2] = b;
            }
        }

        for (int y = 0; y < height; y++)
        {
            for (int x = 0; x < width; x++)
            {
                float r = 0f, g = 0f, b = 0f;
                for (int k = -radius; k <= radius; k++)
                {
                    int sampleY = Math.Clamp(y + k, 0, height - 1);
                    int offset = ((sampleY * width) + x) * 3;
                    float weight = kernel[k + radius];
                    r += horizontal[offset] * weight;
                    g += horizontal[offset + 1] * weight;
                    b += horizontal[offset + 2] * weight;
                }

                int target = ((y * width) + x) * 3;
                vertical[target] = r;
                vertical[target + 1] = g;
                vertical[target + 2] = b;
            }
        }

        return vertical;
    }

    private static float[] BuildKernel(float sigma)
    {
        int radius = Math.Max(1, (int)MathF.Ceiling(sigma * 3f));
        var kernel = new float[(radius * 2) + 1];
        float twoSigmaSquared = 2f * sigma * sigma;
        float sum = 0f;

        for (int i = -radius; i <= radius; i++)
        {
            float weight = MathF.Exp(-(i * i) / twoSigmaSquared);
            kernel[i + radius] = weight;
            sum += weight;
        }

        for (int i = 0; i < kernel.Length; i++)
        {
            kernel[i] /= sum;
        }

        return kernel;
    }

    private static byte ClampToByte(float value) =>
        value <= 0f ? (byte)0 : value >= 255f ? (byte)255 : (byte)(value + 0.5f);
}
