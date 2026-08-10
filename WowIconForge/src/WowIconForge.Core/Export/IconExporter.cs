using SixLabors.ImageSharp;
using SixLabors.ImageSharp.Formats.Png;
using SixLabors.ImageSharp.PixelFormats;
using WowIconForge.Core.Blp;
using WowIconForge.Core.Imaging;

namespace WowIconForge.Core.Export;

public enum IconFormat
{
    Png,
    Blp,
}

public interface IIconExporter
{
    void Save(RgbaImage icon, string path);

    byte[] ToBytes(RgbaImage icon, IconFormat format);
}

/// <summary>Writes a finished icon as PNG or BLP2, picked from the file extension.</summary>
public sealed class IconExporter : IIconExporter
{
    private static readonly PngEncoder Encoder = new()
    {
        ColorType = PngColorType.RgbWithAlpha,
        BitDepth = PngBitDepth.Bit8,
        CompressionLevel = PngCompressionLevel.BestCompression,
    };

    public void Save(RgbaImage icon, string path)
    {
        ArgumentNullException.ThrowIfNull(icon);
        ArgumentException.ThrowIfNullOrWhiteSpace(path);

        string? directory = Path.GetDirectoryName(path);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }

        switch (FormatFor(path))
        {
            case IconFormat.Blp:
                BlpWriter.Save(path, icon);
                break;

            case IconFormat.Png:
            default:
                using (Image<Rgba32> image = icon.ToImageSharp())
                {
                    image.Save(path, Encoder);
                }

                break;
        }
    }

    public byte[] ToBytes(RgbaImage icon, IconFormat format)
    {
        ArgumentNullException.ThrowIfNull(icon);

        if (format == IconFormat.Blp)
        {
            return BlpWriter.ToBytes(icon);
        }

        using Image<Rgba32> image = icon.ToImageSharp();
        using var stream = new MemoryStream();
        image.Save(stream, Encoder);
        return stream.ToArray();
    }

    /// <summary>Anything that is not <c>.blp</c> is written as PNG.</summary>
    public static IconFormat FormatFor(string path) =>
        Path.GetExtension(path).Equals(".blp", StringComparison.OrdinalIgnoreCase)
            ? IconFormat.Blp
            : IconFormat.Png;

    /// <summary>Turns a prompt into a filename that Windows will accept.</summary>
    public static string SuggestFileName(string prompt, long seed, IconFormat format)
    {
        string extension = format == IconFormat.Blp ? "blp" : "png";
        var cleaned = new string((prompt ?? string.Empty)
            .Select(c => char.IsLetterOrDigit(c) ? char.ToLowerInvariant(c) : '_')
            .ToArray())
            .Trim('_');

        while (cleaned.Contains("__", StringComparison.Ordinal))
        {
            cleaned = cleaned.Replace("__", "_", StringComparison.Ordinal);
        }

        if (cleaned.Length > 48)
        {
            cleaned = cleaned[..48].TrimEnd('_');
        }

        if (cleaned.Length == 0)
        {
            cleaned = "icon";
        }

        return $"{cleaned}_{seed}.{extension}";
    }
}
