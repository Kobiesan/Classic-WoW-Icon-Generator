using System.Security.Cryptography;
using SixLabors.ImageSharp;
using SixLabors.ImageSharp.PixelFormats;
using WowIconForge.Core.Imaging;

namespace WowIconForge.Core.Compositing;

/// <summary>
/// A user-supplied border template (typically a 64x64 RGBA PNG) together with a
/// content-derived cache key.
/// </summary>
/// <remarks>
/// The key is a hash of the pixel data rather than the file path plus timestamp:
/// editing a template and saving it under the same name must invalidate the
/// cached content mask, and two different paths holding identical art should
/// share one.
/// </remarks>
public sealed class BorderTemplate
{
    private BorderTemplate(RgbaImage image, string key, string? sourcePath)
    {
        Image = image;
        Key = key;
        SourcePath = sourcePath;
    }

    public RgbaImage Image { get; }

    /// <summary>Stable identity of this template's pixels, used for mask caching.</summary>
    public string Key { get; }

    /// <summary>Where it was loaded from, when it came from disk.</summary>
    public string? SourcePath { get; }

    public int Width => Image.Width;

    public int Height => Image.Height;

    public static BorderTemplate FromImage(RgbaImage image, string? sourcePath = null)
    {
        ArgumentNullException.ThrowIfNull(image);
        return new BorderTemplate(image, ComputeKey(image), sourcePath);
    }

    /// <summary>Loads a template from any image format ImageSharp can read.</summary>
    /// <exception cref="BorderTemplateException">The file is missing or unreadable.</exception>
    public static BorderTemplate Load(string path)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);

        if (!File.Exists(path))
        {
            throw new BorderTemplateException($"Border template not found: {path}");
        }

        RgbaImage pixels;
        try
        {
            using Image<Rgba32> loaded = SixLabors.ImageSharp.Image.Load<Rgba32>(path);
            pixels = loaded.ToRgbaImage();
        }
        catch (Exception ex) when (ex is not BorderTemplateException)
        {
            throw new BorderTemplateException($"Could not read border template '{path}': {ex.Message}", ex);
        }

        return new BorderTemplate(pixels, ComputeKey(pixels), path);
    }

    private static string ComputeKey(RgbaImage image)
    {
        Span<byte> hash = stackalloc byte[32];
        SHA256.HashData(image.Pixels, hash);
        return $"{image.Width}x{image.Height}:{Convert.ToHexString(hash)}";
    }
}

public sealed class BorderTemplateException : Exception
{
    public BorderTemplateException(string message)
        : base(message)
    {
    }

    public BorderTemplateException(string message, Exception innerException)
        : base(message, innerException)
    {
    }
}
