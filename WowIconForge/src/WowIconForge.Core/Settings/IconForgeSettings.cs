using System.Text.Json;
using System.Text.Json.Serialization;
using WowIconForge.Core.Imaging;
using WowIconForge.Core.Inference;

namespace WowIconForge.Core.Settings;

/// <summary>
/// Everything the settings pane edits, persisted as JSON next to the user's
/// other application data.
/// </summary>
public sealed record IconForgeSettings
{
    /// <summary>Folder holding the ONNX model files. Empty until first run.</summary>
    public string ModelDirectory { get; init; } = string.Empty;

    /// <summary>The 64x64 RGBA PNG border template.</summary>
    public string TemplatePath { get; init; } = string.Empty;

    /// <summary>Where Save defaults to.</summary>
    public string OutputDirectory { get; init; } = string.Empty;

    /// <summary>Unsharp strength applied after the 512 to 64 downscale.</summary>
    public float SharpenAmount { get; init; } = UnsharpMask.DefaultAmount;

    public float SharpenSigma { get; init; } = UnsharpMask.DefaultSigma;

    /// <summary>LoRA trigger word prepended to every prompt.</summary>
    public string TriggerWord { get; init; } = PromptBuilder.DefaultTriggerWord;

    /// <summary>Skip DirectML even when it is available.</summary>
    public bool ForceCpu { get; init; }

    [JsonIgnore]
    public bool HasModelDirectory => !string.IsNullOrWhiteSpace(ModelDirectory);

    [JsonIgnore]
    public bool HasTemplate => !string.IsNullOrWhiteSpace(TemplatePath);

    private static readonly JsonSerializerOptions SerializerOptions = new()
    {
        WriteIndented = true,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
    };

    /// <summary>Default location: %AppData%\WowIconForge\settings.json.</summary>
    public static string DefaultPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
        "WowIconForge",
        "settings.json");

    /// <summary>
    /// Loads settings, falling back to defaults when the file is absent or
    /// corrupt. A broken settings file must never stop the app from starting.
    /// </summary>
    public static IconForgeSettings Load(string? path = null)
    {
        path ??= DefaultPath;

        try
        {
            if (!File.Exists(path))
            {
                return new IconForgeSettings();
            }

            string json = File.ReadAllText(path);
            return JsonSerializer.Deserialize<IconForgeSettings>(json, SerializerOptions)
                   ?? new IconForgeSettings();
        }
        catch (Exception ex) when (ex is JsonException or IOException or UnauthorizedAccessException)
        {
            return new IconForgeSettings();
        }
    }

    public void Save(string? path = null)
    {
        path ??= DefaultPath;

        string? directory = Path.GetDirectoryName(path);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }

        File.WriteAllText(path, JsonSerializer.Serialize(this, SerializerOptions));
    }

    /// <summary>Clamps anything a hand-edited file could have put out of range.</summary>
    public IconForgeSettings Normalized() => this with
    {
        SharpenAmount = float.IsNaN(SharpenAmount)
            ? UnsharpMask.DefaultAmount
            : Math.Clamp(SharpenAmount, 0f, UnsharpMask.MaxAmount),
        SharpenSigma = float.IsNaN(SharpenSigma) || SharpenSigma <= 0f
            ? UnsharpMask.DefaultSigma
            : Math.Clamp(SharpenSigma, 0.1f, 10f),
        TriggerWord = string.IsNullOrWhiteSpace(TriggerWord)
            ? PromptBuilder.DefaultTriggerWord
            : TriggerWord.Trim(),
    };
}
