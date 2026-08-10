namespace WowIconForge.Core.Imaging;

/// <summary>A single, non-premultiplied 8-bit RGBA colour.</summary>
public readonly record struct RgbaColor(byte R, byte G, byte B, byte A)
{
    public static readonly RgbaColor Transparent = new(0, 0, 0, 0);

    /// <summary>Packs the colour channels (alpha excluded) into a 24-bit key.</summary>
    public int RgbKey => (R << 16) | (G << 8) | B;

    public static RgbaColor FromRgbKey(int key, byte alpha = 255) =>
        new((byte)((key >> 16) & 0xFF), (byte)((key >> 8) & 0xFF), (byte)(key & 0xFF), alpha);
}

/// <summary>
/// A plain top-down, non-premultiplied 8-bit RGBA pixel buffer.
/// </summary>
/// <remarks>
/// Deliberately dependency free. The BLP reader and writer are ports of the
/// Python decoder in <c>wowicons/blp.py</c> and speak this type only, so the
/// format code stays independent of whichever imaging library the rest of the
/// application happens to use.
/// </remarks>
public sealed class RgbaImage
{
    /// <summary>Bytes per pixel: R, G, B, A.</summary>
    public const int BytesPerPixel = 4;

    public RgbaImage(int width, int height)
        : this(width, height, new byte[checked(width * height * BytesPerPixel)])
    {
    }

    public RgbaImage(int width, int height, byte[] pixels)
    {
        if (width <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(width), width, "Width must be positive.");
        }

        if (height <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(height), height, "Height must be positive.");
        }

        ArgumentNullException.ThrowIfNull(pixels);

        int expected = checked(width * height * BytesPerPixel);
        if (pixels.Length != expected)
        {
            throw new ArgumentException(
                $"Expected {expected} bytes for a {width}x{height} RGBA image, got {pixels.Length}.",
                nameof(pixels));
        }

        Width = width;
        Height = height;
        Pixels = pixels;
    }

    public int Width { get; }

    public int Height { get; }

    /// <summary>Raw RGBA bytes, row-major and top-down.</summary>
    public byte[] Pixels { get; }

    public int PixelCount => Width * Height;

    public bool IsEmpty => PixelCount == 0;

    public int OffsetOf(int x, int y)
    {
        if ((uint)x >= (uint)Width)
        {
            throw new ArgumentOutOfRangeException(nameof(x), x, $"X must be within [0, {Width - 1}].");
        }

        if ((uint)y >= (uint)Height)
        {
            throw new ArgumentOutOfRangeException(nameof(y), y, $"Y must be within [0, {Height - 1}].");
        }

        return (y * Width + x) * BytesPerPixel;
    }

    public RgbaColor GetPixel(int x, int y)
    {
        int i = OffsetOf(x, y);
        return new RgbaColor(Pixels[i], Pixels[i + 1], Pixels[i + 2], Pixels[i + 3]);
    }

    public void SetPixel(int x, int y, RgbaColor colour)
    {
        int i = OffsetOf(x, y);
        Pixels[i] = colour.R;
        Pixels[i + 1] = colour.G;
        Pixels[i + 2] = colour.B;
        Pixels[i + 3] = colour.A;
    }

    /// <summary>Alpha of the pixel at (x, y), without building a colour struct.</summary>
    public byte GetAlpha(int x, int y) => Pixels[OffsetOf(x, y) + 3];

    public void SetAlpha(int x, int y, byte alpha) => Pixels[OffsetOf(x, y) + 3] = alpha;

    public RgbaImage Clone() => new(Width, Height, (byte[])Pixels.Clone());

    /// <summary>Fills the whole buffer with a single colour.</summary>
    public void Fill(RgbaColor colour)
    {
        for (int i = 0; i < Pixels.Length; i += BytesPerPixel)
        {
            Pixels[i] = colour.R;
            Pixels[i + 1] = colour.G;
            Pixels[i + 2] = colour.B;
            Pixels[i + 3] = colour.A;
        }
    }
}
