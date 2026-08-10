using System.Buffers.Binary;
using WowIconForge.Core.Blp;
using WowIconForge.Core.Imaging;
using Xunit;

namespace WowIconForge.Core.Tests;

/// <summary>
/// Decoder tests against synthesized BLP byte streams, mirroring the Python
/// suite this reader was ported from. No binary fixtures, no client files.
/// </summary>
public class BlpDecoderTests
{
    private const ushort Red565 = 0xF800;
    private const ushort Blue565 = 0x001F;

    [Fact]
    public void RejectsNonBlpData()
    {
        BlpException error = Assert.Throws<BlpException>(() => BlpReader.Decode(new byte[400]));
        Assert.Contains("Not a BLP", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void RejectsShortFile()
    {
        Assert.Throws<BlpException>(() => BlpReader.Decode("BLP"u8.ToArray()));
    }

    [Fact]
    public void RejectsImplausibleDimensions()
    {
        byte[] data = BuildBlp2Palettized(2, 2, [0, 0, 0, 0], [TestImages.Red]);
        BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(12), 999_999);

        BlpException error = Assert.Throws<BlpException>(() => BlpReader.Decode(data));
        Assert.Contains("Implausible", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void PaletteIsReadAsBgra()
    {
        byte[] data = BuildBlp2Palettized(1, 1, [0], [new RgbaColor(10, 20, 30, 255)]);

        Assert.Equal(new RgbaColor(10, 20, 30, 255), BlpReader.Decode(data).GetPixel(0, 0));
    }

    [Fact]
    public void PalettizedWithEightBitAlpha()
    {
        byte[] data = BuildBlp2Palettized(
            2, 1, [0, 0], [TestImages.Red], alphaDepth: 8, alphaPlane: [0, 128]);

        RgbaImage image = BlpReader.Decode(data);

        Assert.Equal(0, image.GetPixel(0, 0).A);
        Assert.Equal(128, image.GetPixel(1, 0).A);
    }

    [Fact]
    public void PalettizedWithOneBitAlpha_IsPackedLsbFirst()
    {
        // Pixels 0 and 2 opaque, 1 and 3 transparent -> 0b0101 == 0x05.
        byte[] data = BuildBlp2Palettized(
            4, 1, [0, 0, 0, 0], [TestImages.Red], alphaDepth: 1, alphaPlane: [0x05]);

        RgbaImage image = BlpReader.Decode(data);

        Assert.Equal([255, 0, 255, 0], Enumerable.Range(0, 4).Select(x => (int)image.GetPixel(x, 0).A));
    }

    [Fact]
    public void PalettizedWithFourBitAlpha_TakesTheLowNibbleFirst()
    {
        byte[] data = BuildBlp2Palettized(
            2, 1, [0, 0], [TestImages.Red], alphaDepth: 4, alphaPlane: [0xF0]);

        RgbaImage image = BlpReader.Decode(data);

        Assert.Equal(0, image.GetPixel(0, 0).A);
        Assert.Equal(255, image.GetPixel(1, 0).A);
    }

    [Fact]
    public void Bgra8888IsChannelSwapped()
    {
        byte[] data = BuildBlp2(1, 1, [30, 20, 10, 200], BlpFormat.EncodingBgra8888, alphaDepth: 8);

        Assert.Equal(new RgbaColor(10, 20, 30, 200), BlpReader.Decode(data).GetPixel(0, 0));
    }

    [Fact]
    public void Bgra8888WithoutAlphaBitsIsOpaque()
    {
        byte[] data = BuildBlp2(1, 1, [30, 20, 10, 3], BlpFormat.EncodingBgra8888, alphaDepth: 0);

        Assert.Equal(255, BlpReader.Decode(data).GetPixel(0, 0).A);
    }

    [Fact]
    public void Dxt1InterpolatesTheEndpoints()
    {
        // indices: texel 0 -> c0, 1 -> c1, 2 -> 2/3 c0, 3 -> 1/3 c0
        byte[] block = Dxt1Block(Red565, Blue565, 0b11100100);
        byte[] data = BuildBlp2(4, 4, block, BlpFormat.EncodingDxt, alphaEncoding: BlpFormat.AlphaEncodingDxt1);

        RgbaImage image = BlpReader.Decode(data);

        Assert.Equal(new RgbaColor(255, 0, 0, 255), image.GetPixel(0, 0));
        Assert.Equal(new RgbaColor(0, 0, 255, 255), image.GetPixel(1, 0));
        Assert.Equal(new RgbaColor(170, 0, 85, 255), image.GetPixel(2, 0));
        Assert.Equal(new RgbaColor(85, 0, 170, 255), image.GetPixel(3, 0));
    }

    [Fact]
    public void Dxt1PunchthroughAlphaWhenC0NotGreaterThanC1()
    {
        byte[] block = Dxt1Block(Blue565, Red565, 0b11u << 6);
        byte[] data = BuildBlp2(
            4, 4, block, BlpFormat.EncodingDxt, alphaDepth: 1, alphaEncoding: BlpFormat.AlphaEncodingDxt1);

        Assert.Equal(new RgbaColor(0, 0, 0, 0), BlpReader.Decode(data).GetPixel(3, 0));
    }

    [Fact]
    public void Dxt1IndexThreeIsOpaqueBlackWithoutAlphaBits()
    {
        byte[] block = Dxt1Block(Blue565, Red565, 0b11u << 6);
        byte[] data = BuildBlp2(
            4, 4, block, BlpFormat.EncodingDxt, alphaDepth: 0, alphaEncoding: BlpFormat.AlphaEncodingDxt1);

        Assert.Equal(new RgbaColor(0, 0, 0, 255), BlpReader.Decode(data).GetPixel(3, 0));
    }

    [Fact]
    public void Dxt3ReadsExplicitAlphaNibbles()
    {
        // texel 0 -> 0x0, texel 1 -> 0xF, the rest 0x8.
        ulong nibbles = (0x8888888888888888UL & ~0xFFUL) | 0xF0UL;
        byte[] block = [.. BitConverter.GetBytes(nibbles), .. Dxt1Block(Red565, Blue565, 0)];
        byte[] data = BuildBlp2(
            4, 4, block, BlpFormat.EncodingDxt, alphaDepth: 8, alphaEncoding: BlpFormat.AlphaEncodingDxt3);

        RgbaImage image = BlpReader.Decode(data);

        Assert.Equal(0, image.GetPixel(0, 0).A);
        Assert.Equal(255, image.GetPixel(1, 0).A);
        Assert.Equal(8 * 17, image.GetPixel(2, 0).A);
    }

    [Fact]
    public void Dxt5InterpolatesTheAlphaRamp()
    {
        // a0 > a1 selects the eight-step ramp; index 0 is a0 and index 1 is a1.
        byte[] alpha = [255, 0, 0b001, 0, 0, 0, 0, 0];
        byte[] block = [.. alpha, .. Dxt1Block(Red565, Blue565, 0)];
        byte[] data = BuildBlp2(
            4, 4, block, BlpFormat.EncodingDxt, alphaDepth: 8, alphaEncoding: BlpFormat.AlphaEncodingDxt5);

        RgbaImage image = BlpReader.Decode(data);

        Assert.Equal(0, image.GetPixel(0, 0).A);
        Assert.Equal(255, image.GetPixel(1, 0).A);
    }

    [Fact]
    public void Dxt5ColourBlocksNeverPunchThrough()
    {
        byte[] alpha = [255, 255, 0, 0, 0, 0, 0, 0];
        byte[] block = [.. alpha, .. Dxt1Block(Blue565, Red565, 0b11u << 6)];
        byte[] data = BuildBlp2(
            4, 4, block, BlpFormat.EncodingDxt, alphaDepth: 8, alphaEncoding: BlpFormat.AlphaEncodingDxt5);

        RgbaColor pixel = BlpReader.Decode(data).GetPixel(3, 0);

        Assert.Equal(255, pixel.A);
        Assert.NotEqual(new RgbaColor(0, 0, 0, 255), pixel);
    }

    [Fact]
    public void DxtHandlesDimensionsNotDivisibleByFour()
    {
        byte[] data = BuildBlp2(
            3, 2, Dxt1Block(Red565, Blue565, 0), BlpFormat.EncodingDxt,
            alphaEncoding: BlpFormat.AlphaEncodingDxt1);

        RgbaImage image = BlpReader.Decode(data);

        Assert.Equal(3, image.Width);
        Assert.Equal(2, image.Height);
        Assert.Equal(new RgbaColor(255, 0, 0, 255), image.GetPixel(2, 1));
    }

    [Fact]
    public void TruncatedDxtPayloadIsReported()
    {
        byte[] data = BuildBlp2(
            8, 8, Dxt1Block(Red565, Blue565, 0), BlpFormat.EncodingDxt,
            alphaEncoding: BlpFormat.AlphaEncodingDxt1);

        BlpException error = Assert.Throws<BlpException>(() => BlpReader.Decode(data));
        Assert.Contains("Truncated dxt1", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void UnsupportedEncodingIsReported()
    {
        byte[] data = BuildBlp2(1, 1, new byte[4], encoding: 7);

        Assert.Throws<UnsupportedBlpException>(() => BlpReader.Decode(data));
    }

    [Fact]
    public void JpegVariantIsRejectedClearly()
    {
        byte[] data = BuildBlp1JpegHeaderOnly(8, 8);

        UnsupportedBlpException error = Assert.Throws<UnsupportedBlpException>(() => BlpReader.Decode(data));
        Assert.Contains("JPEG", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Blp1PalettizedDecodes()
    {
        byte[] data = BuildBlp1Palettized(2, 2, [0, 1, 1, 0], [TestImages.Red, TestImages.Green]);

        RgbaImage image = BlpReader.Decode(data);

        Assert.Equal(TestImages.Red, image.GetPixel(0, 0));
        Assert.Equal(TestImages.Green, image.GetPixel(1, 0));
    }

    [Fact]
    public void Blp1PictureTypeFiveIgnoresAlpha()
    {
        byte[] data = BuildBlp1Palettized(
            2, 1, [0, 0], [TestImages.Red], alphaDepth: 8, alphaPlane: [0, 0], pictureType: 5);

        RgbaImage image = BlpReader.Decode(data);

        Assert.Equal(255, image.GetPixel(0, 0).A);
        Assert.Equal(255, image.GetPixel(1, 0).A);
    }

    // --- builders -----------------------------------------------------------

    private static byte[] Dxt1Block(ushort c0, ushort c1, uint indices)
    {
        var block = new byte[8];
        BinaryPrimitives.WriteUInt16LittleEndian(block, c0);
        BinaryPrimitives.WriteUInt16LittleEndian(block.AsSpan(2), c1);
        BinaryPrimitives.WriteUInt32LittleEndian(block.AsSpan(4), indices);
        return block;
    }

    private static byte[] PaletteBytes(IReadOnlyList<RgbaColor> palette)
    {
        var bytes = new byte[BlpFormat.PaletteSizeBytes];
        for (int i = 0; i < palette.Count; i++)
        {
            bytes[(i * 4) + 0] = palette[i].B;
            bytes[(i * 4) + 1] = palette[i].G;
            bytes[(i * 4) + 2] = palette[i].R;
        }

        return bytes;
    }

    private static byte[] BuildBlp2(
        int width,
        int height,
        byte[] payload,
        byte encoding,
        byte alphaDepth = 0,
        byte alphaEncoding = 0,
        IReadOnlyList<RgbaColor>? palette = null)
    {
        int dataOffset = BlpFormat.Blp2HeaderSize + BlpFormat.PaletteSizeBytes;
        var file = new byte[dataOffset + payload.Length];
        Span<byte> span = file;

        BlpFormat.Magic2.CopyTo(span);
        BinaryPrimitives.WriteUInt32LittleEndian(span[4..], BlpFormat.ContentDirect);
        span[8] = encoding;
        span[9] = alphaDepth;
        span[10] = alphaEncoding;
        span[11] = 0;
        BinaryPrimitives.WriteUInt32LittleEndian(span[12..], (uint)width);
        BinaryPrimitives.WriteUInt32LittleEndian(span[16..], (uint)height);
        BinaryPrimitives.WriteUInt32LittleEndian(span[20..], (uint)dataOffset);
        BinaryPrimitives.WriteUInt32LittleEndian(span[84..], (uint)payload.Length);

        PaletteBytes(palette ?? []).CopyTo(span[BlpFormat.Blp2HeaderSize..]);
        payload.CopyTo(span[dataOffset..]);

        return file;
    }

    private static byte[] BuildBlp2Palettized(
        int width,
        int height,
        byte[] indices,
        IReadOnlyList<RgbaColor> palette,
        byte alphaDepth = 0,
        byte[]? alphaPlane = null)
    {
        byte[] payload = [.. indices, .. alphaPlane ?? []];
        return BuildBlp2(width, height, payload, BlpFormat.EncodingPalettized, alphaDepth, 0, palette);
    }

    private static byte[] BuildBlp1Palettized(
        int width,
        int height,
        byte[] indices,
        IReadOnlyList<RgbaColor> palette,
        uint alphaDepth = 0,
        byte[]? alphaPlane = null,
        uint pictureType = 4)
    {
        byte[] payload = [.. indices, .. alphaPlane ?? []];
        int dataOffset = BlpFormat.Blp1HeaderSize + BlpFormat.PaletteSizeBytes;
        var file = new byte[dataOffset + payload.Length];
        Span<byte> span = file;

        BlpFormat.Magic1.CopyTo(span);
        BinaryPrimitives.WriteUInt32LittleEndian(span[4..], BlpFormat.ContentDirect);
        BinaryPrimitives.WriteUInt32LittleEndian(span[8..], alphaDepth);
        BinaryPrimitives.WriteUInt32LittleEndian(span[12..], (uint)width);
        BinaryPrimitives.WriteUInt32LittleEndian(span[16..], (uint)height);
        BinaryPrimitives.WriteUInt32LittleEndian(span[20..], pictureType);
        BinaryPrimitives.WriteUInt32LittleEndian(span[24..], 0);
        BinaryPrimitives.WriteUInt32LittleEndian(span[28..], (uint)dataOffset);
        BinaryPrimitives.WriteUInt32LittleEndian(span[92..], (uint)payload.Length);

        PaletteBytes(palette).CopyTo(span[BlpFormat.Blp1HeaderSize..]);
        payload.CopyTo(span[dataOffset..]);

        return file;
    }

    private static byte[] BuildBlp1JpegHeaderOnly(int width, int height)
    {
        var file = new byte[BlpFormat.Blp1HeaderSize + 4 + 16];
        Span<byte> span = file;

        BlpFormat.Magic1.CopyTo(span);
        BinaryPrimitives.WriteUInt32LittleEndian(span[4..], BlpFormat.ContentJpeg);
        BinaryPrimitives.WriteUInt32LittleEndian(span[8..], 8);
        BinaryPrimitives.WriteUInt32LittleEndian(span[12..], (uint)width);
        BinaryPrimitives.WriteUInt32LittleEndian(span[16..], (uint)height);
        BinaryPrimitives.WriteUInt32LittleEndian(span[20..], 4);
        BinaryPrimitives.WriteUInt32LittleEndian(span[28..], (uint)(BlpFormat.Blp1HeaderSize + 4));
        BinaryPrimitives.WriteUInt32LittleEndian(span[92..], 16);

        return file;
    }
}
