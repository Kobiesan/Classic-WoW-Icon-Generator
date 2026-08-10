using SixLabors.ImageSharp;
using SixLabors.ImageSharp.PixelFormats;

namespace WowIconForge.Core.Imaging;

/// <summary>
/// Conversions between the dependency-free <see cref="RgbaImage"/> used by the
/// BLP layer and ImageSharp's pixel buffers used by the compositing pipeline.
/// </summary>
public static class ImageSharpInterop
{
    public static RgbaImage ToRgbaImage(this Image<Rgba32> image)
    {
        ArgumentNullException.ThrowIfNull(image);

        var result = new RgbaImage(image.Width, image.Height);
        image.CopyPixelDataTo(result.Pixels);
        return result;
    }

    public static Image<Rgba32> ToImageSharp(this RgbaImage image)
    {
        ArgumentNullException.ThrowIfNull(image);

        return Image.LoadPixelData<Rgba32>(image.Pixels, image.Width, image.Height);
    }
}
