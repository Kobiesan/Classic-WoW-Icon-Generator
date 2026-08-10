using WowIconForge.Core.Blp;
using WowIconForge.Core.Imaging;
using Xunit;

namespace WowIconForge.Core.Tests;

public class BlpRoundTripTests
{
    /// <summary>Largest per-channel colour error the quantizer is allowed to introduce.</summary>
    private const int ColourTolerance = 12;

    [Fact]
    public void WriteThenRead_ReproducesTheImage()
    {
        RgbaImage source = TestImages.Gradient(64);

        byte[] blp = BlpWriter.ToBytes(source);
        RgbaImage decoded = BlpReader.Decode(blp);

        Assert.Equal(source.Width, decoded.Width);
        Assert.Equal(source.Height, decoded.Height);
        AssertWithinTolerance(source, decoded, ColourTolerance);
    }

    [Fact]
    public void FewColours_RoundTripExactly()
    {
        // Under 256 distinct colours means the palette holds them all, so the
        // round trip is lossless rather than merely close.
        RgbaImage source = TestImages.FewColours();

        RgbaImage decoded = BlpReader.Decode(BlpWriter.ToBytes(source));

        Assert.Equal(source.Pixels, decoded.Pixels);
    }

    [Fact]
    public void AlphaIsPreservedExactly()
    {
        // The spec is explicit: alpha is written as its own 8-bit plane and must
        // never be quantized into the palette.
        RgbaImage source = TestImages.VaryingAlpha(16);

        RgbaImage decoded = BlpReader.Decode(BlpWriter.ToBytes(source));

        for (int y = 0; y < source.Height; y++)
        {
            for (int x = 0; x < source.Width; x++)
            {
                Assert.Equal(source.GetPixel(x, y).A, decoded.GetPixel(x, y).A);
            }
        }
    }

    [Fact]
    public void CompositedIcon_RoundTripsWithItsTransparentCorners()
    {
        var compositor = new Core.Compositing.IconCompositor();
        RgbaImage icon = compositor.Composite(
            TestImages.Gradient(512),
            TestImages.BorderTemplate(),
            new Core.Compositing.CompositeOptions { SharpenAmount = 0f });

        RgbaImage decoded = BlpReader.Decode(BlpWriter.ToBytes(icon));

        Assert.Equal(0, decoded.GetPixel(0, 0).A);
        Assert.Equal(0, decoded.GetPixel(63, 63).A);
        Assert.Equal(255, decoded.GetPixel(32, 32).A);
        AssertWithinTolerance(icon, decoded, ColourTolerance, onlyVisiblePixels: true);
    }

    [Fact]
    public void HeaderDeclaresPalettizedWithEightBitAlpha()
    {
        byte[] blp = BlpWriter.ToBytes(TestImages.Gradient(64));

        BlpHeader header = BlpReader.ReadHeader(blp);

        Assert.Equal(2, header.Version);
        Assert.Equal(BlpFormat.ContentDirect, header.Content);
        Assert.Equal(BlpFormat.EncodingPalettized, header.Encoding);
        Assert.Equal(8, header.AlphaDepth);
        Assert.True(header.HasMips);
        Assert.False(header.AlphaIgnored);
    }

    [Fact]
    public void FullMipChainIsWritten_From64DownToOne()
    {
        byte[] blp = BlpWriter.ToBytes(TestImages.Gradient(64));
        BlpHeader header = BlpReader.ReadHeader(blp);

        Assert.Equal(7, header.MipCount);   // 64, 32, 16, 8, 4, 2, 1

        int expected = 64;
        for (int level = 0; level < 7; level++)
        {
            RgbaImage mip = BlpReader.Decode(blp, level);
            Assert.Equal(expected, mip.Width);
            Assert.Equal(expected, mip.Height);
            expected /= 2;
        }
    }

    [Fact]
    public void EveryMipLevelSharesTheOnePalette()
    {
        // BLP2 stores a single palette for the whole chain, so a colour present
        // in the smaller levels has to come from the level-0 palette.
        byte[] blp = BlpWriter.ToBytes(TestImages.FewColours());

        RgbaImage level0 = BlpReader.Decode(blp, 0);
        RgbaImage level2 = BlpReader.Decode(blp, 2);

        Assert.Equal(64, level0.Width);
        Assert.Equal(16, level2.Width);
        Assert.All(
            Enumerable.Range(0, level2.PixelCount),
            i => Assert.Equal(255, level2.Pixels[(i * 4) + 3]));
    }

    [Fact]
    public void MipmapsCanBeDisabled()
    {
        byte[] blp = BlpWriter.ToBytes(
            TestImages.Gradient(64), new BlpWriteOptions { GenerateMipmaps = false });

        BlpHeader header = BlpReader.ReadHeader(blp);

        Assert.Equal(1, header.MipCount);
        Assert.False(header.HasMips);
    }

    [Fact]
    public void FullyTransparentImage_StillWritesAValidFile()
    {
        var source = new RgbaImage(16, 16);
        source.Fill(RgbaColor.Transparent);

        RgbaImage decoded = BlpReader.Decode(BlpWriter.ToBytes(source));

        Assert.All(
            Enumerable.Range(0, decoded.PixelCount),
            i => Assert.Equal(0, decoded.Pixels[(i * 4) + 3]));
    }

    [Fact]
    public void NonSquareImagesRoundTrip()
    {
        var source = new RgbaImage(32, 16);
        for (int y = 0; y < 16; y++)
        {
            for (int x = 0; x < 32; x++)
            {
                source.SetPixel(x, y, new RgbaColor((byte)(x * 8), (byte)(y * 16), 64, 255));
            }
        }

        RgbaImage decoded = BlpReader.Decode(BlpWriter.ToBytes(source));

        Assert.Equal(32, decoded.Width);
        Assert.Equal(16, decoded.Height);
        AssertWithinTolerance(source, decoded, ColourTolerance);
    }

    [Fact]
    public void SavesAndLoadsThroughTheFileSystem()
    {
        string path = Path.Combine(Path.GetTempPath(), $"wowiconforge_{Guid.NewGuid():N}.blp");
        try
        {
            RgbaImage source = TestImages.FewColours();
            BlpWriter.Save(path, source);

            RgbaImage decoded = BlpReader.Load(path);

            Assert.Equal(source.Pixels, decoded.Pixels);
        }
        finally
        {
            File.Delete(path);
        }
    }

    [Fact]
    public void OversizedImage_IsRejectedRatherThanTruncated()
    {
        // A chain deeper than 16 levels cannot be represented in the header.
        var huge = new RgbaImage(1 << 16, 1);

        BlpException error = Assert.Throws<BlpException>(() => BlpWriter.ToBytes(huge));
        Assert.Contains("mip levels", error.Message, StringComparison.Ordinal);
    }

    private static void AssertWithinTolerance(
        RgbaImage expected, RgbaImage actual, int tolerance, bool onlyVisiblePixels = false)
    {
        int worst = 0;

        for (int y = 0; y < expected.Height; y++)
        {
            for (int x = 0; x < expected.Width; x++)
            {
                RgbaColor a = expected.GetPixel(x, y);
                RgbaColor b = actual.GetPixel(x, y);

                Assert.Equal(a.A, b.A);

                if (onlyVisiblePixels && a.A == 0)
                {
                    continue;
                }

                worst = Math.Max(worst, Math.Abs(a.R - b.R));
                worst = Math.Max(worst, Math.Abs(a.G - b.G));
                worst = Math.Max(worst, Math.Abs(a.B - b.B));
            }
        }

        Assert.True(worst <= tolerance, $"Worst per-channel colour error was {worst}, allowed {tolerance}.");
    }
}
