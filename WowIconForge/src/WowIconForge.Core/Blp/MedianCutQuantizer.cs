using WowIconForge.Core.Imaging;

namespace WowIconForge.Core.Blp;

/// <summary>A 256-entry RGB palette with nearest-colour lookup.</summary>
public sealed class ColorPalette
{
    private readonly RgbaColor[] _entries;
    private readonly Dictionary<int, byte> _lookupCache = new();

    public ColorPalette(IReadOnlyList<RgbaColor> entries)
    {
        ArgumentNullException.ThrowIfNull(entries);

        if (entries.Count is 0 or > BlpFormat.PaletteEntryCount)
        {
            throw new ArgumentOutOfRangeException(
                nameof(entries), entries.Count,
                $"A palette needs between 1 and {BlpFormat.PaletteEntryCount} entries.");
        }

        _entries = entries.ToArray();

        // The counter must be an int: a byte one wraps at 255 and spins forever
        // on a full 256-entry palette, which is the common case.
        for (int i = 0; i < _entries.Length; i++)
        {
            // First writer wins, so exact colours map to their own entry.
            _lookupCache.TryAdd(_entries[i].RgbKey, (byte)i);
        }
    }

    public IReadOnlyList<RgbaColor> Entries => _entries;

    public int Count => _entries.Length;

    /// <summary>Index of the closest entry by squared RGB distance. Memoised.</summary>
    public byte NearestIndex(byte r, byte g, byte b)
    {
        int key = (r << 16) | (g << 8) | b;
        if (_lookupCache.TryGetValue(key, out byte cached))
        {
            return cached;
        }

        byte best = 0;
        int bestDistance = int.MaxValue;
        for (int i = 0; i < _entries.Length; i++)
        {
            RgbaColor entry = _entries[i];
            int dr = entry.R - r;
            int dg = entry.G - g;
            int db = entry.B - b;
            int distance = (dr * dr) + (dg * dg) + (db * db);
            if (distance < bestDistance)
            {
                bestDistance = distance;
                best = (byte)i;
                if (distance == 0)
                {
                    break;
                }
            }
        }

        _lookupCache[key] = best;
        return best;
    }

    public byte NearestIndex(RgbaColor colour) => NearestIndex(colour.R, colour.G, colour.B);
}

/// <summary>
/// Median-cut colour quantization for the BLP2 palette.
/// </summary>
/// <remarks>
/// Only the colour channels are quantized. Alpha is written per pixel as a
/// separate 8-bit plane, so it survives the round trip exactly - which is both
/// the spec's requirement and the reason icon edges stay clean.
/// <para>
/// Fully transparent pixels are excluded from the histogram: their RGB is
/// arbitrary padding, and letting it vote would spend palette entries on colour
/// nobody can see.
/// </para>
/// </remarks>
public static class MedianCutQuantizer
{
    /// <summary>Pixels with alpha below this contribute no colour to the palette.</summary>
    public const byte DefaultAlphaThreshold = 1;

    public static ColorPalette BuildPalette(
        RgbaImage image,
        int maxColors = BlpFormat.PaletteEntryCount,
        byte alphaThreshold = DefaultAlphaThreshold)
    {
        ArgumentNullException.ThrowIfNull(image);

        if (maxColors is < 1 or > BlpFormat.PaletteEntryCount)
        {
            throw new ArgumentOutOfRangeException(
                nameof(maxColors), maxColors, $"Palette size must be within [1, {BlpFormat.PaletteEntryCount}].");
        }

        Dictionary<int, int> histogram = BuildHistogram(image, alphaThreshold);

        if (histogram.Count == 0)
        {
            // Every pixel is fully transparent; colour is irrelevant but a BLP
            // still needs a palette.
            return new ColorPalette(new[] { RgbaColor.Transparent });
        }

        if (histogram.Count <= maxColors)
        {
            // Exact palette: the round trip is lossless for the colour channels.
            var exact = histogram.Keys
                .OrderBy(key => key)
                .Select(key => RgbaColor.FromRgbKey(key))
                .ToList();
            return new ColorPalette(exact);
        }

        return new ColorPalette(MedianCut(histogram, maxColors));
    }

    private static Dictionary<int, int> BuildHistogram(RgbaImage image, byte alphaThreshold)
    {
        var histogram = new Dictionary<int, int>();
        for (int i = 0; i < image.Pixels.Length; i += RgbaImage.BytesPerPixel)
        {
            if (image.Pixels[i + 3] < alphaThreshold)
            {
                continue;
            }

            int key = (image.Pixels[i] << 16) | (image.Pixels[i + 1] << 8) | image.Pixels[i + 2];
            histogram[key] = histogram.TryGetValue(key, out int count) ? count + 1 : 1;
        }

        return histogram;
    }

    private static List<RgbaColor> MedianCut(Dictionary<int, int> histogram, int maxColors)
    {
        var entries = histogram
            .Select(pair => new ColorCount(RgbaColor.FromRgbKey(pair.Key), pair.Value))
            .ToList();

        var boxes = new List<ColorBox> { new(entries) };

        while (boxes.Count < maxColors)
        {
            ColorBox? target = null;
            int targetIndex = -1;
            int widestSide = 0;
            long largestPopulation = 0;

            for (int i = 0; i < boxes.Count; i++)
            {
                ColorBox candidate = boxes[i];
                if (!candidate.CanSplit)
                {
                    continue;
                }

                int side = candidate.LongestSideLength;
                if (side > widestSide || (side == widestSide && candidate.Population > largestPopulation))
                {
                    widestSide = side;
                    largestPopulation = candidate.Population;
                    target = candidate;
                    targetIndex = i;
                }
            }

            if (target is null)
            {
                // Every remaining box holds a single colour: nothing left to split.
                break;
            }

            (ColorBox left, ColorBox right) = target.Split();
            boxes[targetIndex] = left;
            boxes.Add(right);
        }

        return boxes.Select(box => box.Representative).ToList();
    }

    private readonly record struct ColorCount(RgbaColor Color, int Count);

    /// <summary>An axis-aligned box of colours, split at the population median.</summary>
    private sealed class ColorBox
    {
        private readonly List<ColorCount> _colors;

        public ColorBox(List<ColorCount> colors)
        {
            _colors = colors;

            byte minR = 255, minG = 255, minB = 255;
            byte maxR = 0, maxG = 0, maxB = 0;
            long population = 0;

            foreach (ColorCount entry in colors)
            {
                minR = Math.Min(minR, entry.Color.R);
                minG = Math.Min(minG, entry.Color.G);
                minB = Math.Min(minB, entry.Color.B);
                maxR = Math.Max(maxR, entry.Color.R);
                maxG = Math.Max(maxG, entry.Color.G);
                maxB = Math.Max(maxB, entry.Color.B);
                population += entry.Count;
            }

            RangeR = maxR - minR;
            RangeG = maxG - minG;
            RangeB = maxB - minB;
            Population = population;
        }

        public long Population { get; }

        private int RangeR { get; }

        private int RangeG { get; }

        private int RangeB { get; }

        public int LongestSideLength => Math.Max(RangeR, Math.Max(RangeG, RangeB));

        public bool CanSplit => _colors.Count > 1;

        /// <summary>Population-weighted mean colour of the box.</summary>
        public RgbaColor Representative
        {
            get
            {
                long r = 0, g = 0, b = 0, total = 0;
                foreach (ColorCount entry in _colors)
                {
                    r += (long)entry.Color.R * entry.Count;
                    g += (long)entry.Color.G * entry.Count;
                    b += (long)entry.Color.B * entry.Count;
                    total += entry.Count;
                }

                if (total == 0)
                {
                    return RgbaColor.Transparent;
                }

                return new RgbaColor(
                    (byte)((r + (total / 2)) / total),
                    (byte)((g + (total / 2)) / total),
                    (byte)((b + (total / 2)) / total),
                    255);
            }
        }

        public (ColorBox Left, ColorBox Right) Split()
        {
            Comparison<ColorCount> comparison = LongestSideLength == RangeR
                ? (a, b) => a.Color.R.CompareTo(b.Color.R)
                : LongestSideLength == RangeG
                    ? (a, b) => a.Color.G.CompareTo(b.Color.G)
                    : (a, b) => a.Color.B.CompareTo(b.Color.B);

            _colors.Sort(comparison);

            // Cut where the running pixel count passes half the box population,
            // which keeps both halves similarly busy rather than similarly wide.
            long half = Population / 2;
            long running = 0;
            int splitAt = 0;
            for (int i = 0; i < _colors.Count - 1; i++)
            {
                running += _colors[i].Count;
                splitAt = i + 1;
                if (running >= half)
                {
                    break;
                }
            }

            splitAt = Math.Clamp(splitAt, 1, _colors.Count - 1);

            return (
                new ColorBox(_colors.GetRange(0, splitAt)),
                new ColorBox(_colors.GetRange(splitAt, _colors.Count - splitAt)));
        }
    }
}
