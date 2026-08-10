using WowIconForge.Core.Imaging;

namespace WowIconForge.Core.Blp;

/// <summary>
/// Builds the mip chain a BLP carries, from full size down to 1x1.
/// </summary>
/// <remarks>
/// The box filter averages RGB weighted by alpha. A plain average would pull the
/// colour of fully transparent pixels - which is arbitrary padding - into the
/// visible ones, and the usual symptom is a dark halo creeping inward around
/// icon edges as the mips get smaller. Alpha itself is averaged unweighted.
/// </remarks>
public static class MipmapChain
{
    /// <summary>Full chain: index 0 is the source, the last level is 1x1.</summary>
    public static IReadOnlyList<RgbaImage> Build(RgbaImage source)
    {
        ArgumentNullException.ThrowIfNull(source);

        var levels = new List<RgbaImage> { source };
        RgbaImage current = source;

        while (current.Width > 1 || current.Height > 1)
        {
            current = Downsample(current);
            levels.Add(current);
        }

        return levels;
    }

    /// <summary>Number of levels a chain for these dimensions will hold.</summary>
    public static int LevelCount(int width, int height)
    {
        int levels = 1;
        while (width > 1 || height > 1)
        {
            width = Math.Max(1, width / 2);
            height = Math.Max(1, height / 2);
            levels++;
        }

        return levels;
    }

    /// <summary>Halves each dimension (minimum 1) with an alpha-weighted 2x2 box filter.</summary>
    public static RgbaImage Downsample(RgbaImage source)
    {
        ArgumentNullException.ThrowIfNull(source);

        int width = Math.Max(1, source.Width / 2);
        int height = Math.Max(1, source.Height / 2);
        var result = new RgbaImage(width, height);

        for (int y = 0; y < height; y++)
        {
            for (int x = 0; x < width; x++)
            {
                int x0 = Math.Min((x * 2) + 0, source.Width - 1);
                int x1 = Math.Min((x * 2) + 1, source.Width - 1);
                int y0 = Math.Min((y * 2) + 0, source.Height - 1);
                int y1 = Math.Min((y * 2) + 1, source.Height - 1);

                Span<int> offsets =
                [
                    source.OffsetOf(x0, y0),
                    source.OffsetOf(x1, y0),
                    source.OffsetOf(x0, y1),
                    source.OffsetOf(x1, y1),
                ];

                int alphaSum = 0;
                int weightedR = 0, weightedG = 0, weightedB = 0;
                int plainR = 0, plainG = 0, plainB = 0;

                foreach (int offset in offsets)
                {
                    int alpha = source.Pixels[offset + 3];
                    alphaSum += alpha;
                    weightedR += source.Pixels[offset] * alpha;
                    weightedG += source.Pixels[offset + 1] * alpha;
                    weightedB += source.Pixels[offset + 2] * alpha;
                    plainR += source.Pixels[offset];
                    plainG += source.Pixels[offset + 1];
                    plainB += source.Pixels[offset + 2];
                }

                RgbaColor colour = alphaSum == 0
                    // Nothing visible here, so colour cannot be weighted; keep the
                    // plain average so the RGB stays meaningful if alpha is later
                    // painted back in.
                    ? new RgbaColor(Average(plainR), Average(plainG), Average(plainB), 0)
                    : new RgbaColor(
                        DivideRounded(weightedR, alphaSum),
                        DivideRounded(weightedG, alphaSum),
                        DivideRounded(weightedB, alphaSum),
                        Average(alphaSum));

                result.SetPixel(x, y, colour);
            }
        }

        return result;
    }

    private static byte Average(int sumOfFour) => (byte)((sumOfFour + 2) / 4);

    private static byte DivideRounded(int numerator, int denominator) =>
        (byte)Math.Clamp((numerator + (denominator / 2)) / denominator, 0, 255);
}
