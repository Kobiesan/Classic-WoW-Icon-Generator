using System.Collections.Concurrent;

namespace WowIconForge.Core.Compositing;

public interface IContentMaskCache
{
    /// <summary>Returns the mask for a template, deriving it only on first use.</summary>
    ContentMask GetOrDerive(BorderTemplate template);
}

/// <summary>
/// Caches one <see cref="ContentMask"/> per distinct template, keyed by the
/// template's pixel hash.
/// </summary>
/// <remarks>
/// The spec calls for deriving the mask once per template rather than once per
/// generated icon; with a batch of eight that is eight flood fills saved, and
/// the mask is pure a function of the template so caching it is safe.
/// Thread-safe, because generation runs off the UI thread.
/// </remarks>
public sealed class ContentMaskCache : IContentMaskCache
{
    private readonly ConcurrentDictionary<string, ContentMask> _masks = new(StringComparer.Ordinal);
    private readonly Func<BorderTemplate, ContentMask> _derive;
    private int _derivationCount;

    public ContentMaskCache()
        : this(template => ContentMask.Derive(template))
    {
    }

    /// <summary>Overload for tests, which need to observe how often derivation runs.</summary>
    public ContentMaskCache(Func<BorderTemplate, ContentMask> derive)
    {
        ArgumentNullException.ThrowIfNull(derive);
        _derive = derive;
    }

    /// <summary>How many times a mask was actually computed, as opposed to served from cache.</summary>
    public int DerivationCount => Volatile.Read(ref _derivationCount);

    public int Count => _masks.Count;

    public ContentMask GetOrDerive(BorderTemplate template)
    {
        ArgumentNullException.ThrowIfNull(template);

        return _masks.GetOrAdd(template.Key, _ =>
        {
            Interlocked.Increment(ref _derivationCount);
            return _derive(template);
        });
    }

    public void Clear() => _masks.Clear();
}
