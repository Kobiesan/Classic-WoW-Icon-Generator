using WowIconForge.Core.Imaging;

namespace WowIconForge.Core.Compositing;

/// <summary>
/// The region of a border template that generated art is allowed to occupy.
/// </summary>
/// <remarks>
/// Derived exactly as specified:
/// <list type="number">
/// <item>Flood-fill from the template's centre through transparent pixels using
/// 4-connectivity, halting at opaque pixels. That yields the interior.</item>
/// <item>Union the interior with the template's own opaque pixels.</item>
/// </list>
/// Including the opaque pixels matters: art underneath a semi-transparent
/// border edge has to survive masking so it can show through when the border is
/// composited over it. Corners sit outside the flood region (the border ring
/// blocks the fill) and are transparent in the template, so they end up outside
/// the mask and stay fully transparent in the finished icon.
/// </remarks>
public sealed class ContentMask
{
    private readonly bool[] _included;

    private ContentMask(int width, int height, bool[] included, int interiorPixelCount, int opaquePixelCount)
    {
        Width = width;
        Height = height;
        _included = included;
        InteriorPixelCount = interiorPixelCount;
        OpaquePixelCount = opaquePixelCount;
    }

    /// <summary>Alpha at or above this counts as opaque, and blocks the flood fill.</summary>
    public const byte DefaultOpaqueThreshold = 1;

    public int Width { get; }

    public int Height { get; }

    /// <summary>Pixels reached by the flood fill from the centre.</summary>
    public int InteriorPixelCount { get; }

    /// <summary>Pixels the template itself paints.</summary>
    public int OpaquePixelCount { get; }

    public int IncludedPixelCount
    {
        get
        {
            int count = 0;
            foreach (bool included in _included)
            {
                if (included)
                {
                    count++;
                }
            }

            return count;
        }
    }

    /// <summary>
    /// True when the flood fill reached nothing, which means the template's
    /// centre pixel is itself opaque. The mask is then just the template's own
    /// pixels, and generated art will be almost entirely masked away - worth
    /// surfacing in the UI as a bad template rather than silently producing
    /// empty icons.
    /// </summary>
    public bool HasEmptyInterior => InteriorPixelCount == 0;

    public bool Includes(int x, int y) => _included[(y * Width) + x];

    /// <summary>Derives the mask for a template. Cheap enough to run per template, not per icon.</summary>
    public static ContentMask Derive(BorderTemplate template, byte opaqueThreshold = DefaultOpaqueThreshold)
    {
        ArgumentNullException.ThrowIfNull(template);
        return Derive(template.Image, opaqueThreshold);
    }

    public static ContentMask Derive(RgbaImage template, byte opaqueThreshold = DefaultOpaqueThreshold)
    {
        ArgumentNullException.ThrowIfNull(template);

        int width = template.Width;
        int height = template.Height;
        int pixelCount = width * height;

        var isOpaque = new bool[pixelCount];
        int opaqueCount = 0;
        for (int i = 0; i < pixelCount; i++)
        {
            if (template.Pixels[(i * RgbaImage.BytesPerPixel) + 3] >= opaqueThreshold)
            {
                isOpaque[i] = true;
                opaqueCount++;
            }
        }

        // Step 2a: flood-fill the interior from the centre, 4-connected, through
        // transparent pixels only.
        var interior = new bool[pixelCount];
        int interiorCount = 0;
        int centreIndex = ((height / 2) * width) + (width / 2);

        if (!isOpaque[centreIndex])
        {
            var queue = new Queue<int>();
            queue.Enqueue(centreIndex);
            interior[centreIndex] = true;
            interiorCount++;

            while (queue.Count > 0)
            {
                int index = queue.Dequeue();
                int x = index % width;
                int y = index / width;

                if (x > 0)
                {
                    interiorCount += TryEnqueue(index - 1);
                }

                if (x < width - 1)
                {
                    interiorCount += TryEnqueue(index + 1);
                }

                if (y > 0)
                {
                    interiorCount += TryEnqueue(index - width);
                }

                if (y < height - 1)
                {
                    interiorCount += TryEnqueue(index + width);
                }
            }

            int TryEnqueue(int neighbour)
            {
                if (interior[neighbour] || isOpaque[neighbour])
                {
                    return 0;
                }

                interior[neighbour] = true;
                queue.Enqueue(neighbour);
                return 1;
            }
        }

        // Step 2b: union the interior with the template's opaque pixels.
        var included = new bool[pixelCount];
        for (int i = 0; i < pixelCount; i++)
        {
            included[i] = interior[i] || isOpaque[i];
        }

        return new ContentMask(width, height, included, interiorCount, opaqueCount);
    }
}
