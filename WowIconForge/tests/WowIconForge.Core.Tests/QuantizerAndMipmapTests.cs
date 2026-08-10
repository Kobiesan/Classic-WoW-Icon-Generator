using WowIconForge.Core.Blp;
using WowIconForge.Core.Imaging;
using Xunit;

namespace WowIconForge.Core.Tests;

public class MedianCutQuantizerTests
{
    [Fact]
    public void SmallPalettesAreExact()
    {
        ColorPalette palette = MedianCutQuantizer.BuildPalette(TestImages.FewColours());

        Assert.Equal(5, palette.Count);
        Assert.Contains(TestImages.Red with { A = 255 }, palette.Entries);
        Assert.Contains(TestImages.Green with { A = 255 }, palette.Entries);
    }

    [Fact]
    public void LargePalettesAreCappedAt256()
    {
        ColorPalette palette = MedianCutQuantizer.BuildPalette(TestImages.Gradient(128));

        Assert.True(palette.Count <= 256, $"palette held {palette.Count} entries");
        Assert.True(palette.Count > 1);
    }

    [Fact]
    public void PaletteSizeIsConfigurable()
    {
        ColorPalette palette = MedianCutQuantizer.BuildPalette(TestImages.Gradient(64), maxColors: 16);

        Assert.True(palette.Count <= 16);
    }

    [Fact]
    public void FullyTransparentPixelsDoNotSpendPaletteEntries()
    {
        // Half the image is transparent magenta padding, which nobody can see.
        // It must not claim palette space away from the visible half.
        var image = new RgbaImage(8, 8);
        for (int y = 0; y < 8; y++)
        {
            for (int x = 0; x < 8; x++)
            {
                image.SetPixel(x, y, y < 4
                    ? new RgbaColor(255, 0, 255, 0)
                    : new RgbaColor((byte)(x * 30), 40, 50, 255));
            }
        }

        ColorPalette palette = MedianCutQuantizer.BuildPalette(image);

        Assert.DoesNotContain(new RgbaColor(255, 0, 255, 255), palette.Entries);
    }

    [Fact]
    public void AllTransparent_StillYieldsAUsablePalette()
    {
        var image = new RgbaImage(4, 4);
        image.Fill(RgbaColor.Transparent);

        ColorPalette palette = MedianCutQuantizer.BuildPalette(image);

        Assert.Equal(1, palette.Count);
    }

    [Fact]
    public void NearestIndexFindsExactMatches()
    {
        var palette = new ColorPalette([TestImages.Red, TestImages.Green, TestImages.Blue]);

        Assert.Equal(0, palette.NearestIndex(255, 0, 0));
        Assert.Equal(1, palette.NearestIndex(0, 255, 0));
        Assert.Equal(2, palette.NearestIndex(0, 0, 255));
    }

    [Fact]
    public void NearestIndexFallsBackToTheClosestEntry()
    {
        var palette = new ColorPalette([TestImages.Red, TestImages.Blue]);

        Assert.Equal(0, palette.NearestIndex(250, 10, 10));
        Assert.Equal(1, palette.NearestIndex(10, 10, 250));
    }

    [Fact]
    public void QuantizationErrorStaysModestOnAGradient()
    {
        RgbaImage image = TestImages.Gradient(64);
        ColorPalette palette = MedianCutQuantizer.BuildPalette(image);

        double total = 0;
        for (int i = 0; i < image.PixelCount; i++)
        {
            int p = i * 4;
            RgbaColor mapped = palette.Entries[palette.NearestIndex(
                image.Pixels[p], image.Pixels[p + 1], image.Pixels[p + 2])];
            total += Math.Abs(mapped.R - image.Pixels[p])
                     + Math.Abs(mapped.G - image.Pixels[p + 1])
                     + Math.Abs(mapped.B - image.Pixels[p + 2]);
        }

        double meanError = total / (image.PixelCount * 3);
        Assert.True(meanError < 4.0, $"mean per-channel quantization error was {meanError:F2}");
    }

    [Fact]
    public void RejectsInvalidPaletteSizes()
    {
        Assert.Throws<ArgumentOutOfRangeException>(() =>
            MedianCutQuantizer.BuildPalette(TestImages.Gradient(8), maxColors: 0));
        Assert.Throws<ArgumentOutOfRangeException>(() =>
            MedianCutQuantizer.BuildPalette(TestImages.Gradient(8), maxColors: 257));
    }
}

public class MipmapChainTests
{
    [Fact]
    public void ChainRunsFromFullSizeDownToOne()
    {
        IReadOnlyList<RgbaImage> levels = MipmapChain.Build(TestImages.Gradient(64));

        Assert.Equal(7, levels.Count);
        Assert.Equal(64, levels[0].Width);
        Assert.Equal(1, levels[^1].Width);
        Assert.Equal(1, levels[^1].Height);
    }

    [Theory]
    [InlineData(64, 64, 7)]
    [InlineData(32, 32, 6)]
    [InlineData(1, 1, 1)]
    [InlineData(32, 8, 6)]
    public void LevelCountMatchesTheBuiltChain(int width, int height, int expected)
    {
        var source = new RgbaImage(width, height);

        Assert.Equal(expected, MipmapChain.LevelCount(width, height));
        Assert.Equal(expected, MipmapChain.Build(source).Count);
    }

    [Fact]
    public void DownsampleAveragesA2x2Block()
    {
        var source = new RgbaImage(2, 2);
        source.SetPixel(0, 0, new RgbaColor(0, 0, 0, 255));
        source.SetPixel(1, 0, new RgbaColor(100, 100, 100, 255));
        source.SetPixel(0, 1, new RgbaColor(200, 200, 200, 255));
        source.SetPixel(1, 1, new RgbaColor(255, 255, 255, 255));

        RgbaImage half = MipmapChain.Downsample(source);

        Assert.Equal(1, half.Width);
        Assert.InRange(half.GetPixel(0, 0).R, 138, 140);   // (0+100+200+255)/4 = 138.75
    }

    [Fact]
    public void ColourIsWeightedByAlphaSoTransparentPaddingDoesNotBleedIn()
    {
        // Three transparent black pixels and one opaque white one. A plain
        // average would give a dark grey; weighting by alpha keeps it white.
        var source = new RgbaImage(2, 2);
        source.SetPixel(0, 0, new RgbaColor(255, 255, 255, 255));
        source.SetPixel(1, 0, new RgbaColor(0, 0, 0, 0));
        source.SetPixel(0, 1, new RgbaColor(0, 0, 0, 0));
        source.SetPixel(1, 1, new RgbaColor(0, 0, 0, 0));

        RgbaColor result = MipmapChain.Downsample(source).GetPixel(0, 0);

        Assert.Equal(255, result.R);
        Assert.Equal(64, result.A);      // (255+0+0+0)/4
    }

    [Fact]
    public void FullyTransparentBlockStaysTransparent()
    {
        var source = new RgbaImage(2, 2);
        source.Fill(new RgbaColor(10, 20, 30, 0));

        RgbaColor result = MipmapChain.Downsample(source).GetPixel(0, 0);

        Assert.Equal(0, result.A);
    }

    [Fact]
    public void OddDimensionsHalveWithoutOverrunning()
    {
        RgbaImage half = MipmapChain.Downsample(TestImages.Gradient(9));

        Assert.Equal(4, half.Width);
        Assert.Equal(4, half.Height);
    }
}
