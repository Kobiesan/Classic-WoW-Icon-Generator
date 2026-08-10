namespace WowIconForge.Core.Inference;

/// <summary>
/// Applies the LoRA trigger word to prompts.
/// </summary>
/// <remarks>
/// The LoRA is trained on captions of the form
/// <c>"wowicon, &lt;category&gt;, &lt;subject terms&gt;"</c>, so the trigger has
/// to lead every prompt or the style simply does not fire. Users forget, and
/// users who remember sometimes type it themselves - hence the duplicate check.
/// </remarks>
public static class PromptBuilder
{
    public const string DefaultTriggerWord = "wowicon";

    /// <summary>
    /// Returns <paramref name="prompt"/> with the trigger word in front, unless
    /// it is already the leading term.
    /// </summary>
    public static string Build(string? prompt, string? triggerWord = DefaultTriggerWord)
    {
        string body = (prompt ?? string.Empty).Trim().TrimStart(',').Trim();
        string trigger = (triggerWord ?? string.Empty).Trim().TrimEnd(',').Trim();

        if (trigger.Length == 0)
        {
            return body;
        }

        if (body.Length == 0)
        {
            return trigger;
        }

        return HasLeadingTrigger(body, trigger) ? body : $"{trigger}, {body}";
    }

    /// <summary>True when the prompt's first comma-separated term is already the trigger.</summary>
    public static bool HasLeadingTrigger(string prompt, string triggerWord)
    {
        ArgumentNullException.ThrowIfNull(prompt);
        ArgumentNullException.ThrowIfNull(triggerWord);

        int comma = prompt.IndexOf(',', StringComparison.Ordinal);
        string firstTerm = (comma < 0 ? prompt : prompt[..comma]).Trim();
        return firstTerm.Equals(triggerWord.Trim(), StringComparison.OrdinalIgnoreCase);
    }
}

/// <summary>
/// Wraps any <see cref="IIconGenerator"/> so the trigger word is applied to
/// every request, whatever the backing implementation is.
/// </summary>
/// <remarks>
/// A decorator rather than a line inside each generator: "prepend the trigger to
/// every prompt" is then true by construction, including for the stub and for
/// whatever replaces the ONNX generator later. The trigger is read through a
/// delegate so changing it in settings takes effect on the next generation
/// without rebuilding the object graph.
/// </remarks>
public sealed class TriggerWordGenerator : IIconGenerator
{
    private readonly IIconGenerator _inner;
    private readonly Func<string> _triggerWordProvider;

    public TriggerWordGenerator(IIconGenerator inner, Func<string> triggerWordProvider)
    {
        ArgumentNullException.ThrowIfNull(inner);
        ArgumentNullException.ThrowIfNull(triggerWordProvider);

        _inner = inner;
        _triggerWordProvider = triggerWordProvider;
    }

    public TriggerWordGenerator(IIconGenerator inner, string triggerWord = PromptBuilder.DefaultTriggerWord)
        : this(inner, () => triggerWord)
    {
    }

    public bool IsReady => _inner.IsReady;

    public Task<IReadOnlyList<GeneratedImage>> GenerateAsync(
        IconRequest request,
        IProgress<GenerationProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);

        var resolved = request with
        {
            Prompt = PromptBuilder.Build(request.Prompt, _triggerWordProvider()),
        };

        return _inner.GenerateAsync(resolved, progress, cancellationToken);
    }
}
