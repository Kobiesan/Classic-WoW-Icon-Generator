namespace WowIconForge.Core.Inference;

public enum ExecutionProviderKind
{
    /// <summary>DirectML: any DX12-capable GPU, which on Windows is nearly all of them.</summary>
    DirectML,

    /// <summary>The always-available fallback. Slow, but it finishes.</summary>
    Cpu,
}

/// <summary>What the selector settled on, and why.</summary>
public sealed record ExecutionProviderPlan(
    ExecutionProviderKind Provider,
    int DeviceId,
    string Reason)
{
    public bool IsFallback => Provider == ExecutionProviderKind.Cpu;

    public override string ToString() =>
        Provider == ExecutionProviderKind.DirectML
            ? $"DirectML (device {DeviceId}) - {Reason}"
            : $"CPU - {Reason}";
}

/// <summary>
/// Decides between DirectML and the CPU fallback.
/// </summary>
/// <remarks>
/// The decision is kept separate from session creation, and free of any
/// ONNX Runtime types, so it can be unit tested on a machine with no GPU and no
/// native runtime - which includes CI. <see cref="Onnx.OnnxSessionFactory"/> turns a
/// plan into real session options.
/// </remarks>
public sealed class ExecutionProviderSelector
{
    private readonly Func<bool> _directMlAvailable;

    public ExecutionProviderSelector()
        : this(DefaultDirectMlProbe)
    {
    }

    /// <param name="directMlAvailable">
    /// Probe for DirectML support. Injected so tests can drive both branches.
    /// </param>
    public ExecutionProviderSelector(Func<bool> directMlAvailable)
    {
        ArgumentNullException.ThrowIfNull(directMlAvailable);
        _directMlAvailable = directMlAvailable;
    }

    /// <summary>
    /// Picks a provider. <paramref name="forceCpu"/> comes from settings, for
    /// users whose driver misbehaves under DirectML.
    /// </summary>
    public ExecutionProviderPlan Select(bool forceCpu = false, int deviceId = 0)
    {
        if (forceCpu)
        {
            return new ExecutionProviderPlan(
                ExecutionProviderKind.Cpu, 0, "CPU was requested in settings.");
        }

        if (deviceId < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(deviceId), deviceId, "Device id cannot be negative.");
        }

        bool available;
        try
        {
            available = _directMlAvailable();
        }
        catch (Exception ex)
        {
            // A probe that throws is a probe that failed: fall back rather than
            // taking the whole generation down with it.
            return new ExecutionProviderPlan(
                ExecutionProviderKind.Cpu, 0, $"DirectML check failed ({ex.GetType().Name}), using CPU.");
        }

        return available
            ? new ExecutionProviderPlan(
                ExecutionProviderKind.DirectML, deviceId, "DirectML is available.")
            : new ExecutionProviderPlan(
                ExecutionProviderKind.Cpu, 0, "No DirectML-capable device found, using CPU.");
    }

    /// <summary>DirectML ships on Windows 10 1903 and later; anywhere else there is none.</summary>
    private static bool DefaultDirectMlProbe() =>
        OperatingSystem.IsWindowsVersionAtLeast(10, 0, 18362);
}
