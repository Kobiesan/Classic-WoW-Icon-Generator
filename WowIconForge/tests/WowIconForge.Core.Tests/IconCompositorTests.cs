using WowIconForge.Core.Compositing;
using WowIconForge.Core.Imaging;
using Xunit;

namespace WowIconForge.Core.Tests;

public class IconCompositorTests
{
    private static readonly CompositeOptions NoSharpen = new() { SharpenAmount = 0f };

    [Fact]
    public void Corners_AreFullyTransparent()
    {
        // The requirement the spec calls out by name: with a template whose
        // corners are known-transparent, the finished icon's corners must be too.
        var compositor = new IconCompositor();
        RgbaImage art = TestImages.Solid(512, TestImages.Red);

        RgbaImage icon = compositor.Composite(art, TestImages.BorderTemplate(), NoSharpen);

        Assert.Equal(0, icon.GetPixel(0, 0).A);
        Assert.Equal(0, icon.GetPixel(63, 0).A);
        Assert.Equal(0, icon.GetPixel(0, 63).A);
        Assert.Equal(0, icon.GetPixel(63, 63).A);
        Assert.Equal(0, icon.GetPixel(2, 2).A);
    }

    [Fact]
    public void Interior_ShowsTheGeneratedArt()
    {
        var compositor = new IconCompositor();
        RgbaImage art = TestImages.Solid(512, TestImages.Red);

        RgbaImage icon = compositor.Composite(art, TestImages.BorderTemplate(), NoSharpen);

        RgbaColor centre = icon.GetPixel(32, 32);
        Assert.Equal(255, centre.A);
        Assert.Equal(TestImages.Red.R, centre.R);
        Assert.Equal(TestImages.Red.G, centre.G);
    }

    [Fact]
    public void Border_IsDrawnOverTheArt()
    {
        var compositor = new IconCompositor();
        RgbaImage art = TestImages.Solid(512, TestImages.Red);

        RgbaImage icon = compositor.Composite(art, TestImages.BorderTemplate(), NoSharpen);

        RgbaColor onRing = icon.GetPixel(5, 32);
        Assert.Equal(255, onRing.A);
        Assert.Equal(TestImages.Gold.R, onRing.R);
        Assert.Equal(TestImages.Gold.G, onRing.G);
        Assert.Equal(TestImages.Gold.B, onRing.B);
    }

    [Fact]
    public void Output_MatchesTheTemplateSize()
    {
        var compositor = new IconCompositor();

        RgbaImage icon = compositor.Composite(
            TestImages.Solid(512, TestImages.Blue), TestImages.BorderTemplate(size: 32), NoSharpen);

        Assert.Equal(32, icon.Width);
        Assert.Equal(32, icon.Height);
    }

    [Fact]
    public void SemiTransparentBorder_LetsArtShowThrough()
    {
        // Art under a half-opaque border must survive masking, then blend.
        var template = new RgbaImage(8, 8);
        template.Fill(RgbaColor.Transparent);
        for (int i = 0; i < 8; i++)
        {
            template.SetPixel(i, 0, new RgbaColor(0, 0, 255, 128));
        }

        var compositor = new IconCompositor();
        RgbaImage art = TestImages.Solid(8, TestImages.Red);

        RgbaImage icon = compositor.Composite(art, BorderTemplate.FromImage(template), NoSharpen);

        RgbaColor blended = icon.GetPixel(4, 0);
        Assert.Equal(255, blended.A);
        Assert.InRange(blended.R, 100, 140);   // red bleeding through
        Assert.InRange(blended.B, 100, 140);   // blue border on top
    }

    [Fact]
    public void MaskIsDerivedOncePerTemplate_NotPerIcon()
    {
        var cache = new ContentMaskCache();
        var compositor = new IconCompositor(cache);
        var template = TestImages.BorderTemplate();
        RgbaImage art = TestImages.Solid(512, TestImages.Red);

        for (int i = 0; i < 8; i++)
        {
            compositor.Composite(art, template, NoSharpen);
        }

        Assert.Equal(1, cache.DerivationCount);
    }

    [Fact]
    public void IdenticalTemplatesShareOneCacheEntry()
    {
        var cache = new ContentMaskCache();
        var compositor = new IconCompositor(cache);
        RgbaImage art = TestImages.Solid(512, TestImages.Red);

        // Two separately constructed but pixel-identical templates.
        compositor.Composite(art, TestImages.BorderTemplate(), NoSharpen);
        compositor.Composite(art, TestImages.BorderTemplate(), NoSharpen);

        Assert.Equal(1, cache.DerivationCount);
        Assert.Equal(1, cache.Count);
    }

    [Fact]
    public void DifferentTemplatesGetTheirOwnMask()
    {
        var cache = new ContentMaskCache();
        var compositor = new IconCompositor(cache);
        RgbaImage art = TestImages.Solid(512, TestImages.Red);

        compositor.Composite(art, TestImages.BorderTemplate(inset: 4), NoSharpen);
        compositor.Composite(art, TestImages.BorderTemplate(inset: 6), NoSharpen);

        Assert.Equal(2, cache.DerivationCount);
    }

    [Fact]
    public void SharpeningIsOptional()
    {
        var compositor = new IconCompositor();
        // The art has to carry detail that survives the 8x downscale. A linear
        // gradient is unchanged by blurring, and fine stripes average into a
        // flat field at 64x64 - either would pass this test for the wrong
        // reason. Coarse blocks leave real edges at the target size.
        RgbaImage art = TestImages.Blocks(512, blockSize: 64);
        var template = TestImages.BorderTemplate();

        RgbaImage soft = compositor.Composite(art, template, new CompositeOptions { SharpenAmount = 0f });
        RgbaImage sharp = compositor.Composite(art, template, new CompositeOptions { SharpenAmount = 1.5f });

        Assert.False(soft.Pixels.SequenceEqual(sharp.Pixels));
    }

    [Fact]
    public void SharpeningLeavesAFlatImageAlone()
    {
        // Nothing to sharpen means nothing changes, however high the strength.
        RgbaImage flat = TestImages.Solid(64, TestImages.Red);

        RgbaImage sharpened = UnsharpMask.Apply(flat, amount: 2.0f);

        Assert.Equal(flat.Pixels, sharpened.Pixels);
    }

    [Fact]
    public void ZeroSharpenAmountReturnsAnUntouchedCopy()
    {
        RgbaImage source = TestImages.FewColours(32);

        RgbaImage result = UnsharpMask.Apply(source, amount: 0f);

        Assert.Equal(source.Pixels, result.Pixels);
        Assert.NotSame(source.Pixels, result.Pixels);
    }

    [Fact]
    public void SharpeningIncreasesLocalContrast()
    {
        // A single bright pixel on a dark field must get brighter, and the ring
        // around it darker, which is what an unsharp mask does.
        var source = new RgbaImage(9, 9);
        source.Fill(new RgbaColor(100, 100, 100, 255));
        source.SetPixel(4, 4, new RgbaColor(180, 180, 180, 255));

        RgbaImage sharpened = UnsharpMask.Apply(source, amount: 1.0f);

        Assert.True(sharpened.GetPixel(4, 4).R > 180, "the peak should rise");
        Assert.True(sharpened.GetPixel(4, 6).R < 100, "its surroundings should dip");
    }

    [Fact]
    public void SharpeningNeverTouchesAlpha()
    {
        RgbaImage source = TestImages.VaryingAlpha(16);

        RgbaImage sharpened = UnsharpMask.Apply(source, amount: 2.0f);

        for (int y = 0; y < source.Height; y++)
        {
            for (int x = 0; x < source.Width; x++)
            {
                Assert.Equal(source.GetPixel(x, y).A, sharpened.GetPixel(x, y).A);
            }
        }
    }

    [Theory]
    [InlineData(-0.1f)]
    [InlineData(99f)]
    public void OutOfRangeSharpenAmountIsRejected(float amount)
    {
        Assert.Throws<ArgumentOutOfRangeException>(() =>
            UnsharpMask.Apply(TestImages.Solid(8, TestImages.Red), amount));
    }

    [Fact]
    public void SharpeningDoesNotDisturbTheCorners()
    {
        // Sharpening runs before masking, so it must not be able to resurrect
        // alpha outside the content mask.
        var compositor = new IconCompositor();

        RgbaImage icon = compositor.Composite(
            TestImages.Gradient(512),
            TestImages.BorderTemplate(),
            new CompositeOptions { SharpenAmount = 3.0f });

        Assert.Equal(0, icon.GetPixel(0, 0).A);
        Assert.Equal(0, icon.GetPixel(63, 63).A);
    }

    [Fact]
    public void Downscale_UsesLanczosAndAveragesDetail()
    {
        // A checkerboard at 512 must resolve to a mid-tone at 64, not to one of
        // the two extremes, which is what a nearest-neighbour resize would do.
        var art = new RgbaImage(512, 512);
        for (int y = 0; y < 512; y++)
        {
            for (int x = 0; x < 512; x++)
            {
                art.SetPixel(x, y, ((x + y) % 2 == 0) ? new RgbaColor(0, 0, 0, 255) : new RgbaColor(255, 255, 255, 255));
            }
        }

        RgbaImage resized = IconCompositor.Resize(art, 64, 64);

        RgbaColor sample = resized.GetPixel(32, 32);
        Assert.InRange(sample.R, 100, 155);
    }

    [Fact]
    public void ArtIsNotMutatedByCompositing()
    {
        var compositor = new IconCompositor();
        RgbaImage art = TestImages.Solid(64, TestImages.Red);
        byte[] before = (byte[])art.Pixels.Clone();

        compositor.Composite(art, TestImages.BorderTemplate(), NoSharpen);

        Assert.Equal(before, art.Pixels);
    }

    [Fact]
    public void MismatchedMaskSize_IsRejected()
    {
        ContentMask mask = ContentMask.Derive(TestImages.BorderTemplate(size: 64));
        RgbaImage art = TestImages.Solid(32, TestImages.Red);

        Assert.Throws<ArgumentException>(() => IconCompositor.ApplyMask(art, mask));
    }

    [Fact]
    public void CompositeOver_MatchesTheSourceOverFormula()
    {
        var top = new RgbaImage(1, 1);
        top.SetPixel(0, 0, new RgbaColor(255, 0, 0, 128));
        var bottom = new RgbaImage(1, 1);
        bottom.SetPixel(0, 0, new RgbaColor(0, 0, 255, 255));

        RgbaImage result = IconCompositor.AlphaCompositeOver(top, bottom);
        RgbaColor pixel = result.GetPixel(0, 0);

        // outA = 1; outR = (255*0.502 + 0*0.498)/1; outB = (0 + 255*0.498)/1
        Assert.Equal(255, pixel.A);
        Assert.InRange(pixel.R, 126, 130);
        Assert.InRange(pixel.B, 125, 129);
    }

    [Fact]
    public void FullyTransparentResult_HasZeroedColourChannels()
    {
        var transparent = new RgbaImage(1, 1);
        transparent.SetPixel(0, 0, new RgbaColor(200, 200, 200, 0));

        RgbaImage result = IconCompositor.AlphaCompositeOver(transparent, transparent);
        RgbaColor pixel = result.GetPixel(0, 0);

        Assert.Equal(new RgbaColor(0, 0, 0, 0), pixel);
    }

    [Fact]
    public void NullArguments_AreRejected()
    {
        var compositor = new IconCompositor();

        Assert.Throws<ArgumentNullException>(() =>
            compositor.Composite(null!, TestImages.BorderTemplate()));
        Assert.Throws<ArgumentNullException>(() =>
            compositor.Composite(TestImages.Solid(64, TestImages.Red), null!));
    }
}
