using WowIconForge.Core.Compositing;
using WowIconForge.Core.Imaging;

namespace WowIconForge.Core.Tests;

/// <summary>Synthetic images with known-good properties, shared across the tests.</summary>
public static class TestImages
{
    public static readonly RgbaColor Red = new(255, 0, 0, 255);
    public static readonly RgbaColor Green = new(0, 255, 0, 255);
    public static readonly RgbaColor Blue = new(0, 0, 255, 255);
    public static readonly RgbaColor Gold = new(196, 160, 64, 255);

    public static RgbaImage Solid(int size, RgbaColor colour)
    {
        var image = new RgbaImage(size, size);
        image.Fill(colour);
        return image;
    }

    /// <summary>
    /// A border template shaped like a real icon frame: an opaque ring inset
    /// from the edge, a transparent interior, and - critically - transparent
    /// corners outside the ring.
    /// </summary>
    /// <param name="size">Template edge length.</param>
    /// <param name="inset">How far the ring sits in from the edge.</param>
    /// <param name="thickness">Ring thickness in pixels.</param>
    public static RgbaImage BorderTemplateImage(int size = 64, int inset = 4, int thickness = 3)
    {
        var image = new RgbaImage(size, size);
        image.Fill(RgbaColor.Transparent);

        int outer = inset;
        int inner = inset + thickness;

        for (int y = 0; y < size; y++)
        {
            for (int x = 0; x < size; x++)
            {
                bool insideOuter = x >= outer && y >= outer && x < size - outer && y < size - outer;
                bool insideInner = x >= inner && y >= inner && x < size - inner && y < size - inner;

                if (insideOuter && !insideInner)
                {
                    image.SetPixel(x, y, Gold);
                }
            }
        }

        return image;
    }

    public static BorderTemplate BorderTemplate(int size = 64, int inset = 4, int thickness = 3) =>
        Compositing.BorderTemplate.FromImage(BorderTemplateImage(size, inset, thickness));

    /// <summary>A template with no gap: every pixel opaque.</summary>
    public static RgbaImage FullyOpaqueTemplate(int size = 8) => Solid(size, Gold);

    /// <summary>Deterministic multi-colour art, for exercising quantization.</summary>
    public static RgbaImage Gradient(int size, byte alpha = 255)
    {
        var image = new RgbaImage(size, size);
        for (int y = 0; y < size; y++)
        {
            for (int x = 0; x < size; x++)
            {
                image.SetPixel(x, y, new RgbaColor(
                    (byte)(x * 255 / Math.Max(1, size - 1)),
                    (byte)(y * 255 / Math.Max(1, size - 1)),
                    (byte)((x + y) * 255 / Math.Max(1, (size - 1) * 2)),
                    alpha));
            }
        }

        return image;
    }

    /// <summary>Art using only a handful of colours, so a palette can hold it exactly.</summary>
    public static RgbaImage FewColours(int size = 64)
    {
        RgbaColor[] palette = [Red, Green, Blue, Gold, new RgbaColor(10, 20, 30, 255)];
        var image = new RgbaImage(size, size);
        for (int y = 0; y < size; y++)
        {
            for (int x = 0; x < size; x++)
            {
                image.SetPixel(x, y, palette[(x + y) % palette.Length]);
            }
        }

        return image;
    }

    /// <summary>
    /// A coarse checkerboard whose edges survive an 8x downscale, for tests that
    /// need real detail at 64x64 rather than a pattern that averages flat.
    /// </summary>
    public static RgbaImage Blocks(int size, int blockSize)
    {
        var image = new RgbaImage(size, size);
        for (int y = 0; y < size; y++)
        {
            for (int x = 0; x < size; x++)
            {
                bool dark = ((x / blockSize) + (y / blockSize)) % 2 == 0;
                image.SetPixel(x, y, dark
                    ? new RgbaColor(30, 30, 40, 255)
                    : new RgbaColor(220, 210, 190, 255));
            }
        }

        return image;
    }

    /// <summary>Every distinct alpha value the round trip has to preserve.</summary>
    public static RgbaImage VaryingAlpha(int size = 16)
    {
        var image = new RgbaImage(size, size);
        for (int y = 0; y < size; y++)
        {
            for (int x = 0; x < size; x++)
            {
                image.SetPixel(x, y, new RgbaColor(200, 100, 50, (byte)((x + (y * size)) % 256)));
            }
        }

        return image;
    }
}
