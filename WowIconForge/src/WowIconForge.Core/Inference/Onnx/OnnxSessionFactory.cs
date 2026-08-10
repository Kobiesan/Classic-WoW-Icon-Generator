using Microsoft.ML.OnnxRuntime;

namespace WowIconForge.Core.Inference.Onnx;

/// <summary>
/// Turns an <see cref="ExecutionProviderPlan"/> into ONNX Runtime session
/// options, and loads the model files from a directory chosen at runtime.
/// </summary>
/// <remarks>
/// This is the only type in Core that touches ONNX Runtime, which keeps the
/// native dependency off every unit-tested path. DirectML failures at session
/// creation are caught and retried on CPU: the provider probe can say yes on a
/// machine whose driver still refuses the actual device.
/// </remarks>
public sealed class OnnxSessionFactory
{
    private readonly ExecutionProviderSelector _selector;

    public OnnxSessionFactory(ExecutionProviderSelector? selector = null)
    {
        _selector = selector ?? new ExecutionProviderSelector();
    }

    /// <summary>The plan used for the most recently created session, for display in the UI.</summary>
    public ExecutionProviderPlan? LastPlan { get; private set; }

    public SessionOptions CreateSessionOptions(ExecutionProviderPlan plan)
    {
        ArgumentNullException.ThrowIfNull(plan);

        var options = new SessionOptions
        {
            GraphOptimizationLevel = GraphOptimizationLevel.ORT_ENABLE_ALL,
            LogSeverityLevel = OrtLoggingLevel.ORT_LOGGING_LEVEL_WARNING,
        };

        if (plan.Provider == ExecutionProviderKind.DirectML)
        {
            // DirectML requires sequential execution.
            options.ExecutionMode = ExecutionMode.ORT_SEQUENTIAL;
            options.EnableMemoryPattern = false;
            options.AppendExecutionProvider_DML(plan.DeviceId);
        }

        return options;
    }

    /// <summary>
    /// Opens a model, preferring DirectML and falling back to CPU if the device
    /// refuses the session.
    /// </summary>
    public InferenceSession CreateSession(string modelPath, bool forceCpu = false, int deviceId = 0)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(modelPath);

        if (!File.Exists(modelPath))
        {
            throw new FileNotFoundException($"Model file not found: {modelPath}", modelPath);
        }

        ExecutionProviderPlan plan = _selector.Select(forceCpu, deviceId);

        if (plan.Provider == ExecutionProviderKind.DirectML)
        {
            try
            {
                var session = new InferenceSession(modelPath, CreateSessionOptions(plan));
                LastPlan = plan;
                return session;
            }
            catch (Exception ex) when (ex is OnnxRuntimeException or DllNotFoundException or EntryPointNotFoundException)
            {
                plan = new ExecutionProviderPlan(
                    ExecutionProviderKind.Cpu, 0, $"DirectML session failed ({ex.GetType().Name}), using CPU.");
            }
        }

        var cpuSession = new InferenceSession(modelPath, CreateSessionOptions(plan));
        LastPlan = plan;
        return cpuSession;
    }
}
