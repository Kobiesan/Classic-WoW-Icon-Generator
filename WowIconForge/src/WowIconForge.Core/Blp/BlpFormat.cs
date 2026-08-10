namespace WowIconForge.Core.Blp;

/// <summary>
/// Layout constants for Blizzard's BLP1 and BLP2 textures.
/// </summary>
/// <remarks>
/// BLP2 header (148 bytes, little endian), followed by an always-present 256
/// entry BGRA palette:
/// <code>
/// char   magic[4]        "BLP2"
/// uint32 content         0 = JPEG, 1 = direct
/// uint8  encoding        1 = palettized, 2 = DXT, 3 = BGRA8888
/// uint8  alphaDepth      0, 1, 4 or 8
/// uint8  alphaEncoding   0 = DXT1, 1 = DXT3, 7 = DXT5
/// uint8  hasMips
/// uint32 width, height
/// uint32 mipOffsets[16]
/// uint32 mipSizes[16]
/// </code>
/// BLP1 header (156 bytes) instead reads
/// <c>magic, content, alphaDepth, width, height, pictureType, hasMips</c>
/// followed by the same two mip tables, then either a palette (direct) or a
/// shared JPEG header (JPEG).
/// </remarks>
public static class BlpFormat
{
    public static ReadOnlySpan<byte> Magic1 => "BLP1"u8;

    public static ReadOnlySpan<byte> Magic2 => "BLP2"u8;

    public const int Blp1HeaderSize = 156;
    public const int Blp2HeaderSize = 148;
    public const int PaletteEntryCount = 256;
    public const int PaletteSizeBytes = PaletteEntryCount * 4;
    public const int MaxMipLevels = 16;

    public const uint ContentJpeg = 0;
    public const uint ContentDirect = 1;

    public const byte EncodingPalettized = 1;
    public const byte EncodingDxt = 2;
    public const byte EncodingBgra8888 = 3;

    public const byte AlphaEncodingDxt1 = 0;
    public const byte AlphaEncodingDxt3 = 1;
    public const byte AlphaEncodingDxt5 = 7;

    /// <summary>BLP1 picture types whose alpha channel is present but unused.</summary>
    public const uint Blp1OpaquePictureType = 5;
}

public class BlpException : Exception
{
    public BlpException(string message)
        : base(message)
    {
    }

    public BlpException(string message, Exception innerException)
        : base(message, innerException)
    {
    }
}

/// <summary>A well-formed BLP using a variant this codec does not implement.</summary>
public sealed class UnsupportedBlpException : BlpException
{
    public UnsupportedBlpException(string message)
        : base(message)
    {
    }
}
