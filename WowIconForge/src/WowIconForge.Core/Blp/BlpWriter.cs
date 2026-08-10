using System.Buffers.Binary;
using WowIconForge.Core.Imaging;

namespace WowIconForge.Core.Blp;

public sealed record BlpWriteOptions
{
    public static readonly BlpWriteOptions Default = new();

    /// <summary>Write the full mip chain down to 1x1, as the game expects.</summary>
    public bool GenerateMipmaps { get; init; } = true;

    public int MaxPaletteColors { get; init; } = BlpFormat.PaletteEntryCount;

    /// <summary>Pixels below this alpha do not contribute colour to the palette.</summary>
    public byte PaletteAlphaThreshold { get; init; } = MedianCutQuantizer.DefaultAlphaThreshold;
}

/// <summary>
/// Writes BLP2 textures: palettized, 256 colours, with a full 8-bit alpha plane.
/// </summary>
/// <remarks>
/// One palette is shared by every mip level, which is how the format works, so
/// it is built from the full-resolution image and reused as the chain shrinks.
/// Alpha is never quantized - it is written verbatim, one byte per pixel, after
/// the index plane of each level.
/// </remarks>
public static class BlpWriter
{
    public static byte[] ToBytes(RgbaImage image, BlpWriteOptions? options = null)
    {
        using var stream = new MemoryStream();
        Write(stream, image, options);
        return stream.ToArray();
    }

    public static void Save(string path, RgbaImage image, BlpWriteOptions? options = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);

        using FileStream stream = File.Create(path);
        Write(stream, image, options);
    }

    public static void Write(Stream stream, RgbaImage image, BlpWriteOptions? options = null)
    {
        ArgumentNullException.ThrowIfNull(stream);
        ArgumentNullException.ThrowIfNull(image);
        options ??= BlpWriteOptions.Default;

        IReadOnlyList<RgbaImage> levels = options.GenerateMipmaps
            ? MipmapChain.Build(image)
            : new[] { image };

        if (levels.Count > BlpFormat.MaxMipLevels)
        {
            throw new BlpException(
                $"A {image.Width}x{image.Height} image needs {levels.Count} mip levels, " +
                $"but BLP stores at most {BlpFormat.MaxMipLevels}.");
        }

        ColorPalette palette = MedianCutQuantizer.BuildPalette(
            image, options.MaxPaletteColors, options.PaletteAlphaThreshold);

        byte[][] encodedLevels = levels.Select(level => EncodeLevel(level, palette)).ToArray();

        var mipOffsets = new uint[BlpFormat.MaxMipLevels];
        var mipSizes = new uint[BlpFormat.MaxMipLevels];
        uint offset = BlpFormat.Blp2HeaderSize + BlpFormat.PaletteSizeBytes;
        for (int i = 0; i < encodedLevels.Length; i++)
        {
            mipOffsets[i] = offset;
            mipSizes[i] = (uint)encodedLevels[i].Length;
            offset += (uint)encodedLevels[i].Length;
        }

        WriteHeader(stream, image, levels.Count > 1, mipOffsets, mipSizes);
        WritePalette(stream, palette);

        foreach (byte[] level in encodedLevels)
        {
            stream.Write(level, 0, level.Length);
        }
    }

    /// <summary>Index plane followed by the 8-bit alpha plane.</summary>
    private static byte[] EncodeLevel(RgbaImage level, ColorPalette palette)
    {
        int pixelCount = level.PixelCount;
        var buffer = new byte[pixelCount * 2];

        for (int i = 0; i < pixelCount; i++)
        {
            int p = i * RgbaImage.BytesPerPixel;
            buffer[i] = palette.NearestIndex(level.Pixels[p], level.Pixels[p + 1], level.Pixels[p + 2]);
            buffer[pixelCount + i] = level.Pixels[p + 3];
        }

        return buffer;
    }

    private static void WriteHeader(
        Stream stream, RgbaImage image, bool hasMips, uint[] mipOffsets, uint[] mipSizes)
    {
        Span<byte> header = stackalloc byte[BlpFormat.Blp2HeaderSize];
        header.Clear();

        BlpFormat.Magic2.CopyTo(header);
        BinaryPrimitives.WriteUInt32LittleEndian(header[4..], BlpFormat.ContentDirect);
        header[8] = BlpFormat.EncodingPalettized;
        header[9] = 8;                                  // alphaDepth: full 8-bit alpha
        header[10] = 0;                                 // alphaEncoding: unused when palettized
        header[11] = (byte)(hasMips ? 1 : 0);
        BinaryPrimitives.WriteUInt32LittleEndian(header[12..], (uint)image.Width);
        BinaryPrimitives.WriteUInt32LittleEndian(header[16..], (uint)image.Height);

        for (int i = 0; i < BlpFormat.MaxMipLevels; i++)
        {
            BinaryPrimitives.WriteUInt32LittleEndian(header[(20 + (i * 4))..], mipOffsets[i]);
            BinaryPrimitives.WriteUInt32LittleEndian(header[(84 + (i * 4))..], mipSizes[i]);
        }

        stream.Write(header);
    }

    /// <summary>256 BGRA entries. Unused slots are zero; the palette alpha byte is ignored by readers.</summary>
    private static void WritePalette(Stream stream, ColorPalette palette)
    {
        Span<byte> buffer = stackalloc byte[BlpFormat.PaletteSizeBytes];
        buffer.Clear();

        for (int i = 0; i < palette.Count; i++)
        {
            RgbaColor entry = palette.Entries[i];
            buffer[(i * 4) + 0] = entry.B;
            buffer[(i * 4) + 1] = entry.G;
            buffer[(i * 4) + 2] = entry.R;
            buffer[(i * 4) + 3] = 0;
        }

        stream.Write(buffer);
    }
}
