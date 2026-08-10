using WowIconForge.Core.Compositing;
using WowIconForge.Core.Imaging;
using Xunit;

namespace WowIconForge.Core.Tests;

public class ContentMaskTests
{
    [Fact]
    public void Interior_IsReachedFromTheCentre()
    {
        ContentMask mask = ContentMask.Derive(TestImages.BorderTemplate());

        Assert.True(mask.Includes(32, 32));
        Assert.True(mask.Includes(10, 32));
        Assert.False(mask.HasEmptyInterior);
    }

    [Fact]
    public void BorderRing_IsIncludedSoArtSurvivesUnderneathIt()
    {
        // Step 2 unions the interior with the template's opaque pixels: art
        // beneath a semi-transparent border edge has to survive masking.
        ContentMask mask = ContentMask.Derive(TestImages.BorderTemplate(inset: 4, thickness: 3));

        Assert.True(mask.Includes(4, 32));
        Assert.True(mask.Includes(6, 32));
    }

    [Fact]
    public void Corners_AreOutsideTheMask()
    {
        // The ring blocks the flood fill, and the corners are transparent in the
        // template, so they belong to neither half of the union.
        ContentMask mask = ContentMask.Derive(TestImages.BorderTemplate());

        Assert.False(mask.Includes(0, 0));
        Assert.False(mask.Includes(63, 0));
        Assert.False(mask.Includes(0, 63));
        Assert.False(mask.Includes(63, 63));
        Assert.False(mask.Includes(2, 2));
    }

    [Fact]
    public void FloodFill_IsFourConnectedAndDoesNotLeakDiagonally()
    {
        // A ring whose only gap is a diagonal step. With 4-connectivity the fill
        // must stay inside; with 8-connectivity it would escape to the corners.
        var template = new RgbaImage(9, 9);
        template.Fill(RgbaColor.Transparent);

        for (int i = 0; i < 9; i++)
        {
            template.SetPixel(i, 2, TestImages.Gold);
            template.SetPixel(i, 6, TestImages.Gold);
            template.SetPixel(2, i, TestImages.Gold);
            template.SetPixel(6, i, TestImages.Gold);
        }

        // Punch a diagonal-only opening at the corner of the ring.
        template.SetPixel(2, 2, RgbaColor.Transparent);

        ContentMask mask = ContentMask.Derive(BorderTemplate.FromImage(template));

        Assert.True(mask.Includes(4, 4));       // interior
        Assert.False(mask.Includes(1, 1));      // outside, only diagonally adjacent to the gap
        Assert.False(mask.Includes(0, 0));
    }

    [Fact]
    public void OpaqueThreshold_TreatsSemiTransparentBorderPixelsAsBorder()
    {
        var template = new RgbaImage(9, 9);
        template.Fill(RgbaColor.Transparent);
        for (int i = 0; i < 9; i++)
        {
            // A faint ring: alpha 8 everywhere on the frame.
            template.SetPixel(i, 2, new RgbaColor(200, 200, 200, 8));
            template.SetPixel(i, 6, new RgbaColor(200, 200, 200, 8));
            template.SetPixel(2, i, new RgbaColor(200, 200, 200, 8));
            template.SetPixel(6, i, new RgbaColor(200, 200, 200, 8));
        }

        var border = BorderTemplate.FromImage(template);

        // Default threshold of 1: any non-zero alpha blocks, so the ring holds.
        ContentMask strict = ContentMask.Derive(border);
        Assert.True(strict.Includes(4, 4));
        Assert.False(strict.Includes(0, 0));

        // Threshold above the ring's alpha: it no longer blocks, and the fill
        // escapes to cover the whole image.
        ContentMask loose = ContentMask.Derive(border, opaqueThreshold: 64);
        Assert.True(loose.Includes(0, 0));
    }

    [Fact]
    public void OpaqueCentre_YieldsEmptyInteriorAndIsReported()
    {
        // A template with no hole cannot host art. The UI needs to know rather
        // than silently producing blank icons.
        ContentMask mask = ContentMask.Derive(
            BorderTemplate.FromImage(TestImages.FullyOpaqueTemplate(8)));

        Assert.True(mask.HasEmptyInterior);
        Assert.Equal(0, mask.InteriorPixelCount);
        Assert.Equal(64, mask.OpaquePixelCount);
        Assert.True(mask.Includes(0, 0));   // still covered, by the opaque half of the union
    }

    [Fact]
    public void FullyTransparentTemplate_FillsEverything()
    {
        var template = new RgbaImage(8, 8);
        template.Fill(RgbaColor.Transparent);

        ContentMask mask = ContentMask.Derive(BorderTemplate.FromImage(template));

        Assert.Equal(64, mask.InteriorPixelCount);
        Assert.Equal(64, mask.IncludedPixelCount);
        Assert.Equal(0, mask.OpaquePixelCount);
    }

    [Fact]
    public void IncludedPixelCount_IsTheUnionNotTheSum()
    {
        ContentMask mask = ContentMask.Derive(TestImages.BorderTemplate());

        Assert.Equal(mask.InteriorPixelCount + mask.OpaquePixelCount, mask.IncludedPixelCount);
        Assert.True(mask.IncludedPixelCount < 64 * 64, "corners must remain excluded");
    }
}
