namespace WowIconForge.Core.Inference.Onnx;

/// <summary>
/// The real generator: Stable Diffusion over ONNX Runtime, DirectML preferred
/// with a CPU fallback.
/// </summary>
/// <remarks>
/// <para><b>Not implemented yet, by design.</b> This phase stubs inference
/// behind <see cref="IIconGenerator"/> so compositing and BLP export could be
/// built and tested before any model files exist. What is here is the part that
/// does not need a model: locating and validating the model directory, and
/// choosing an execution provider.</para>
/// <para>What the denoising loop still needs, roughly in order:
/// a CLIP tokenizer over <c>tokenizer/vocab.json</c> and <c>merges.txt</c>;
/// text-encoder inference for the prompt and the negative prompt; a scheduler
/// (Euler ancestral or DPM++ 2M); the per-step U-Net loop applying
/// classifier-free guidance at <see cref="IconRequest.CfgScale"/>; and a VAE
/// decode of the final latent into 512x512 RGB.</para>
/// <para>Until then <see cref="IsReady"/> reports whether the models are on
/// disk, and <see cref="GenerateAsync"/> throws rather than pretending.</para>
/// </remarks>
public sealed class OnnxIconGenerator : IIconGenerator
{
    private readonly OnnxSessionFactory _sessionFactory;

    public OnnxIconGenerator(string modelDirectory, OnnxSessionFactory? sessionFactory = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(modelDirectory);

        ModelDirectory = modelDirectory;
        _sessionFactory = sessionFactory ?? new OnnxSessionFactory();
    }

    public string ModelDirectory { get; }

    /// <summary>Re-probes the directory each time, so dropping files in is picked up without a restart.</summary>
    public ModelDirectoryStatus Status => ModelLayout.Probe(ModelDirectory);

    public bool IsReady => Status.IsComplete;

    /// <summary>The provider the last session used, once inference is wired up.</summary>
    public ExecutionProviderPlan? ExecutionProvider => _sessionFactory.LastPlan;

    public Task<IReadOnlyList<GeneratedImage>> GenerateAsync(
        IconRequest request,
        IProgress<GenerationProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);
        request.Validate();

        ModelDirectoryStatus status = Status;
        if (!status.IsComplete)
        {
            throw new InvalidOperationException(status.ToUserMessage());
        }

        throw new NotImplementedException(
            "ONNX inference is not wired up yet. Use StubIconGenerator until the " +
            "denoising loop lands; see the remarks on OnnxIconGenerator for what it needs.");
    }
}
