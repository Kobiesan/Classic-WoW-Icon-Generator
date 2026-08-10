using System.Buffers.Binary;
using WowIconForge.Core.Imaging;

namespace WowIconForge.Core.Blp;

/// <summary>Parsed BLP header, normalised across BLP1 and BLP2.</summary>
public sealed class BlpHeader
{
    public required int Version { get; init; }

    public required uint Content { get; init; }

    public required byte Encoding { get; init; }

    public required byte AlphaDepth { get; init; }

    public required byte AlphaEncoding { get; init; }

    public required bool HasMips { get; init; }

    public required int Width { get; init; }

    public required int Height { get; init; }

    public required uint[] MipOffsets { get; init; }

    public required uint[] MipSizes { get; init; }

    public RgbaColor[] Palette { get; init; } = [];

    public uint PictureType { get; init; }

    /// <summary>True when the file carries alpha bits that should not be used.</summary>
    public bool AlphaIgnored =>
        AlphaDepth == 0 ||
        (Version == 1 && PictureType == BlpFormat.Blp1OpaquePictureType);

    public int MipCount
    {
        get
        {
            int count = 0;
            for (int i = 0; i < BlpFormat.MaxMipLevels; i++)
            {
                if (MipOffsets[i] == 0 || MipSizes[i] == 0)
                {
                    break;
                }

                count++;
            }

            return Math.Max(count, 1);
        }
    }
}

/// <summary>
/// Reads BLP1 and BLP2 textures into straight RGBA.
/// </summary>
/// <remarks>
/// A direct port of the Python decoder in <c>wowicons/blp.py</c>, kept
/// behaviourally identical so the two stay comparable: palettized with 1, 4 or
/// 8-bit alpha, DXT1/DXT3/DXT5, and BGRA8888. The JPEG-compressed BLP1 variant
/// is rejected rather than guessed at - vanilla <c>Interface/Icons</c> does not
/// use it, and its channel order was never verified against a real Blizzard file.
/// </remarks>
public static class BlpReader
{
    public static RgbaImage Load(string path, int mipLevel = 0)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        return Decode(File.ReadAllBytes(path), mipLevel);
    }

    public static RgbaImage Decode(byte[] data, int mipLevel = 0)
    {
        ArgumentNullException.ThrowIfNull(data);

        BlpHeader header = ReadHeader(data);
        (int width, int height) = MipDimensions(header, mipLevel);
        ReadOnlySpan<byte> payload = MipData(data, header, mipLevel);

        bool opaque = header.AlphaIgnored;
        byte effectiveAlphaDepth = opaque ? (byte)0 : header.AlphaDepth;

        if (header.Content == BlpFormat.ContentJpeg)
        {
            throw new UnsupportedBlpException(
                "JPEG-compressed BLP1 is not supported. Vanilla Interface/Icons files are " +
                "palettized BLP1, so this is almost certainly not an icon.");
        }

        RgbaImage image = header.Encoding switch
        {
            BlpFormat.EncodingPalettized =>
                DecodePalettized(payload, width, height, header.Palette, effectiveAlphaDepth),
            BlpFormat.EncodingDxt =>
                DecodeDxt(payload, width, height, DxtFlavour(header), punchthroughAlpha: !opaque),
            BlpFormat.EncodingBgra8888 =>
                DecodeBgra8888(payload, width, height, opaque),
            _ => throw new UnsupportedBlpException($"Unsupported BLP encoding {header.Encoding}."),
        };

        return image;
    }

    public static BlpHeader ReadHeader(byte[] data)
    {
        ArgumentNullException.ThrowIfNull(data);

        if (data.Length < 8)
        {
            throw new BlpException("File is too short to be a BLP.");
        }

        ReadOnlySpan<byte> magic = data.AsSpan(0, 4);
        if (magic.SequenceEqual(BlpFormat.Magic2))
        {
            return ReadHeaderBlp2(data);
        }

        if (magic.SequenceEqual(BlpFormat.Magic1))
        {
            return ReadHeaderBlp1(data);
        }

        throw new BlpException($"Not a BLP file (magic '{System.Text.Encoding.ASCII.GetString(magic)}').");
    }

    private static BlpHeader ReadHeaderBlp1(byte[] data)
    {
        if (data.Length < BlpFormat.Blp1HeaderSize)
        {
            throw new BlpException("File is truncated inside the BLP1 header.");
        }

        var span = data.AsSpan();
        uint content = BinaryPrimitives.ReadUInt32LittleEndian(span[4..]);
        uint alphaDepth = BinaryPrimitives.ReadUInt32LittleEndian(span[8..]);
        int width = (int)BinaryPrimitives.ReadUInt32LittleEndian(span[12..]);
        int height = (int)BinaryPrimitives.ReadUInt32LittleEndian(span[16..]);
        uint pictureType = BinaryPrimitives.ReadUInt32LittleEndian(span[20..]);
        uint hasMips = BinaryPrimitives.ReadUInt32LittleEndian(span[24..]);

        ValidateDimensions(width, height);

        var header = new BlpHeader
        {
            Version = 1,
            Content = content,
            Encoding = content == BlpFormat.ContentDirect ? BlpFormat.EncodingPalettized : (byte)0,
            AlphaDepth = (byte)alphaDepth,
            AlphaEncoding = 0,
            HasMips = hasMips != 0,
            Width = width,
            Height = height,
            MipOffsets = ReadUInt32Table(span, 28),
            MipSizes = ReadUInt32Table(span, 92),
            PictureType = pictureType,
            Palette = content == BlpFormat.ContentDirect
                ? ReadPalette(data, BlpFormat.Blp1HeaderSize)
                : [],
        };

        if (content is not (BlpFormat.ContentDirect or BlpFormat.ContentJpeg))
        {
            throw new UnsupportedBlpException($"Unknown BLP1 content type {content}.");
        }

        return header;
    }

    private static BlpHeader ReadHeaderBlp2(byte[] data)
    {
        if (data.Length < BlpFormat.Blp2HeaderSize + BlpFormat.PaletteSizeBytes)
        {
            throw new BlpException("File is truncated inside the BLP2 header.");
        }

        var span = data.AsSpan();
        int width = (int)BinaryPrimitives.ReadUInt32LittleEndian(span[12..]);
        int height = (int)BinaryPrimitives.ReadUInt32LittleEndian(span[16..]);
        ValidateDimensions(width, height);

        return new BlpHeader
        {
            Version = 2,
            Content = BinaryPrimitives.ReadUInt32LittleEndian(span[4..]),
            Encoding = data[8],
            AlphaDepth = data[9],
            AlphaEncoding = data[10],
            HasMips = data[11] != 0,
            Width = width,
            Height = height,
            MipOffsets = ReadUInt32Table(span, 20),
            MipSizes = ReadUInt32Table(span, 84),
            // BLP2 always reserves palette space, even for DXT and BGRA content.
            Palette = ReadPalette(data, BlpFormat.Blp2HeaderSize),
        };
    }

    private static uint[] ReadUInt32Table(ReadOnlySpan<byte> span, int offset)
    {
        var table = new uint[BlpFormat.MaxMipLevels];
        for (int i = 0; i < BlpFormat.MaxMipLevels; i++)
        {
            table[i] = BinaryPrimitives.ReadUInt32LittleEndian(span[(offset + (i * 4))..]);
        }

        return table;
    }

    /// <summary>Reads the 256 entry BGRA palette, keeping only the colour channels.</summary>
    private static RgbaColor[] ReadPalette(byte[] data, int offset)
    {
        if (data.Length < offset + BlpFormat.PaletteSizeBytes)
        {
            throw new BlpException("File is truncated inside the palette.");
        }

        var palette = new RgbaColor[BlpFormat.PaletteEntryCount];
        for (int i = 0; i < BlpFormat.PaletteEntryCount; i++)
        {
            int p = offset + (i * 4);
            // Stored BGRA; the palette's own alpha byte is unreliable, so real
            // alpha always comes from the separate plane sized by AlphaDepth.
            palette[i] = new RgbaColor(data[p + 2], data[p + 1], data[p], 255);
        }

        return palette;
    }

    private static void ValidateDimensions(int width, int height)
    {
        if (width <= 0 || height <= 0)
        {
            throw new BlpException($"Invalid dimensions {width}x{height}.");
        }

        if (width > 16384 || height > 16384)
        {
            throw new BlpException($"Implausible dimensions {width}x{height}.");
        }
    }

    public static (int Width, int Height) MipDimensions(BlpHeader header, int level)
    {
        ArgumentNullException.ThrowIfNull(header);
        return (Math.Max(header.Width >> level, 1), Math.Max(header.Height >> level, 1));
    }

    private static ReadOnlySpan<byte> MipData(byte[] data, BlpHeader header, int level)
    {
        if (level is < 0 or >= BlpFormat.MaxMipLevels)
        {
            throw new BlpException($"Mip level {level} is out of range.");
        }

        uint offset = header.MipOffsets[level];
        uint size = header.MipSizes[level];

        if (offset == 0)
        {
            throw new BlpException($"Mip level {level} is not present.");
        }

        if (offset >= data.Length)
        {
            throw new BlpException($"Mip level {level} starts past the end of the file.");
        }

        // Some writers leave the last level's size at zero; take the remainder.
        int length = size == 0
            ? data.Length - (int)offset
            : (int)Math.Min(size, (uint)(data.Length - offset));

        return data.AsSpan((int)offset, length);
    }

    private static string DxtFlavour(BlpHeader header) => header.AlphaEncoding switch
    {
        BlpFormat.AlphaEncodingDxt1 => "dxt1",
        BlpFormat.AlphaEncodingDxt3 => "dxt3",
        BlpFormat.AlphaEncodingDxt5 => "dxt5",
        _ => throw new UnsupportedBlpException(
            $"Unsupported DXT alpha encoding {header.AlphaEncoding}."),
    };

    internal static RgbaImage DecodePalettized(
        ReadOnlySpan<byte> payload, int width, int height, RgbaColor[] palette, byte alphaDepth)
    {
        int pixelCount = width * height;

        if (palette.Length < BlpFormat.PaletteEntryCount)
        {
            throw new BlpException("Palettized image without a full 256 entry palette.");
        }

        if (payload.Length < pixelCount)
        {
            throw new BlpException("Truncated palette index data.");
        }

        byte[] alpha = DecodeAlphaPlane(payload, pixelCount, pixelCount, alphaDepth);
        var image = new RgbaImage(width, height);

        for (int i = 0; i < pixelCount; i++)
        {
            RgbaColor entry = palette[payload[i]];
            int p = i * RgbaImage.BytesPerPixel;
            image.Pixels[p] = entry.R;
            image.Pixels[p + 1] = entry.G;
            image.Pixels[p + 2] = entry.B;
            image.Pixels[p + 3] = alpha[i];
        }

        return image;
    }

    private static byte[] DecodeAlphaPlane(
        ReadOnlySpan<byte> payload, int alphaOffset, int pixelCount, byte alphaDepth)
    {
        var alpha = new byte[pixelCount];

        switch (alphaDepth)
        {
            case 0:
                Array.Fill(alpha, (byte)255);
                return alpha;

            case 1:
            {
                int needed = (pixelCount + 7) / 8;
                if (payload.Length < alphaOffset + needed)
                {
                    throw new BlpException("Truncated 1-bit alpha bitmap.");
                }

                for (int i = 0; i < pixelCount; i++)
                {
                    byte packed = payload[alphaOffset + (i >> 3)];
                    alpha[i] = ((packed >> (i & 7)) & 1) != 0 ? (byte)255 : (byte)0;
                }

                return alpha;
            }

            case 4:
            {
                int needed = (pixelCount + 1) / 2;
                if (payload.Length < alphaOffset + needed)
                {
                    throw new BlpException("Truncated 4-bit alpha bitmap.");
                }

                for (int i = 0; i < pixelCount; i++)
                {
                    byte packed = payload[alphaOffset + (i >> 1)];
                    int nibble = (i & 1) == 0 ? packed & 0x0F : (packed >> 4) & 0x0F;
                    alpha[i] = (byte)(nibble * 17); // 0x0 -> 0, 0xF -> 255
                }

                return alpha;
            }

            case 8:
                if (payload.Length < alphaOffset + pixelCount)
                {
                    throw new BlpException("Truncated 8-bit alpha bitmap.");
                }

                payload.Slice(alphaOffset, pixelCount).CopyTo(alpha);
                return alpha;

            default:
                throw new UnsupportedBlpException($"Unsupported alpha depth {alphaDepth}.");
        }
    }

    internal static RgbaImage DecodeBgra8888(
        ReadOnlySpan<byte> payload, int width, int height, bool opaque)
    {
        int pixelCount = width * height;
        if (payload.Length < pixelCount * 4)
        {
            throw new BlpException("Truncated BGRA8888 data.");
        }

        var image = new RgbaImage(width, height);
        for (int i = 0; i < pixelCount; i++)
        {
            int p = i * 4;
            image.Pixels[p] = payload[p + 2];
            image.Pixels[p + 1] = payload[p + 1];
            image.Pixels[p + 2] = payload[p];
            image.Pixels[p + 3] = opaque ? (byte)255 : payload[p + 3];
        }

        return image;
    }

    internal static RgbaImage DecodeDxt(
        ReadOnlySpan<byte> payload, int width, int height, string flavour, bool punchthroughAlpha)
    {
        int blockBytes = flavour == "dxt1" ? 8 : 16;
        int blocksX = (width + 3) / 4;
        int blocksY = (height + 3) / 4;
        int expected = blocksX * blocksY * blockBytes;

        if (payload.Length < expected)
        {
            throw new BlpException(
                $"Truncated {flavour} data: got {payload.Length} bytes, need {expected}.");
        }

        var image = new RgbaImage(width, height);
        var table = new RgbaColor[4];
        var blockAlpha = new byte[16];
        // Allocated once: a stackalloc here would grow the frame per block.
        Span<byte> ramp = stackalloc byte[8];
        int position = 0;

        for (int by = 0; by < blocksY; by++)
        {
            for (int bx = 0; bx < blocksX; bx++)
            {
                bool hasExplicitAlpha = false;

                if (flavour == "dxt3")
                {
                    hasExplicitAlpha = true;
                    for (int i = 0; i < 8; i++)
                    {
                        byte packed = payload[position + i];
                        blockAlpha[i * 2] = (byte)((packed & 0x0F) * 17);
                        blockAlpha[(i * 2) + 1] = (byte)(((packed >> 4) & 0x0F) * 17);
                    }

                    position += 8;
                }
                else if (flavour == "dxt5")
                {
                    hasExplicitAlpha = true;
                    byte a0 = payload[position];
                    byte a1 = payload[position + 1];
                    ramp[0] = a0;
                    ramp[1] = a1;
                    if (a0 > a1)
                    {
                        for (int i = 1; i < 7; i++)
                        {
                            ramp[i + 1] = (byte)((((7 - i) * a0) + (i * a1)) / 7);
                        }
                    }
                    else
                    {
                        for (int i = 1; i < 5; i++)
                        {
                            ramp[i + 1] = (byte)((((5 - i) * a0) + (i * a1)) / 5);
                        }

                        ramp[6] = 0;
                        ramp[7] = 255;
                    }

                    ulong bits = 0;
                    for (int i = 0; i < 6; i++)
                    {
                        bits |= (ulong)payload[position + 2 + i] << (8 * i);
                    }

                    for (int i = 0; i < 16; i++)
                    {
                        blockAlpha[i] = ramp[(int)((bits >> (3 * i)) & 0x07)];
                    }

                    position += 8;
                }

                ushort c0 = (ushort)(payload[position] | (payload[position + 1] << 8));
                ushort c1 = (ushort)(payload[position + 2] | (payload[position + 3] << 8));
                // Only DXT1 uses the c0 <= c1 encoding to signal transparency;
                // DXT3 and DXT5 colour blocks are always four opaque colours.
                BuildColourTable(c0, c1, allowPunchthrough: flavour == "dxt1", table);

                uint indices = BinaryPrimitives.ReadUInt32LittleEndian(payload[(position + 4)..]);
                position += 8;

                for (int py = 0; py < 4; py++)
                {
                    int y = (by * 4) + py;
                    if (y >= height)
                    {
                        break;
                    }

                    for (int px = 0; px < 4; px++)
                    {
                        int x = (bx * 4) + px;
                        if (x >= width)
                        {
                            continue;
                        }

                        int texel = (py * 4) + px;
                        RgbaColor colour = table[(int)((indices >> (2 * texel)) & 0x03)];
                        byte alpha = hasExplicitAlpha
                            ? blockAlpha[texel]
                            : punchthroughAlpha ? colour.A : (byte)255;

                        image.SetPixel(x, y, colour with { A = alpha });
                    }
                }
            }
        }

        return image;
    }

    private static void BuildColourTable(ushort c0, ushort c1, bool allowPunchthrough, RgbaColor[] table)
    {
        (byte r0, byte g0, byte b0) = Rgb565(c0);
        (byte r1, byte g1, byte b1) = Rgb565(c1);

        table[0] = new RgbaColor(r0, g0, b0, 255);
        table[1] = new RgbaColor(r1, g1, b1, 255);

        if (c0 > c1 || !allowPunchthrough)
        {
            table[2] = new RgbaColor(
                (byte)(((2 * r0) + r1) / 3), (byte)(((2 * g0) + g1) / 3), (byte)(((2 * b0) + b1) / 3), 255);
            table[3] = new RgbaColor(
                (byte)((r0 + (2 * r1)) / 3), (byte)((g0 + (2 * g1)) / 3), (byte)((b0 + (2 * b1)) / 3), 255);
        }
        else
        {
            table[2] = new RgbaColor(
                (byte)((r0 + r1) / 2), (byte)((g0 + g1) / 2), (byte)((b0 + b1) / 2), 255);
            table[3] = new RgbaColor(0, 0, 0, 0);
        }
    }

    private static (byte R, byte G, byte B) Rgb565(ushort value)
    {
        int r = (value >> 11) & 0x1F;
        int g = (value >> 5) & 0x3F;
        int b = value & 0x1F;
        return (
            (byte)((r << 3) | (r >> 2)),
            (byte)((g << 2) | (g >> 4)),
            (byte)((b << 3) | (b >> 2)));
    }
}
