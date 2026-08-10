namespace WowIconForge.Core.Inference;

/// <summary>One file the model directory is expected to contain.</summary>
/// <param name="RelativePath">Path under the model directory, using forward slashes.</param>
/// <param name="Description">Plain-language description, shown in the first-run wizard.</param>
/// <param name="Required">False for files the pipeline can run without.</param>
public sealed record ModelFile(string RelativePath, string Description, bool Required = true);

/// <summary>
/// The on-disk layout the ONNX generator expects, and the check that drives the
/// first-run wizard.
/// </summary>
/// <remarks>
/// This is the standard export layout produced by
/// <c>optimum-cli export onnx --model &lt;sd-model&gt;</c>, which is what a user
/// following any online guide will end up with. Nothing is embedded in the exe:
/// the directory is chosen at runtime and validated here.
/// </remarks>
public static class ModelLayout
{
    public static IReadOnlyList<ModelFile> Files { get; } =
    [
        new("unet/model.onnx", "The denoising U-Net - the main model, usually the largest file."),
        new("vae_decoder/model.onnx", "Turns the model's latent output into a visible image."),
        new("text_encoder/model.onnx", "Turns your prompt into something the model understands."),
        new("tokenizer/vocab.json", "Vocabulary used to read your prompt."),
        new("tokenizer/merges.txt", "Companion file to the vocabulary."),
        new("vae_encoder/model.onnx", "Only needed for image-to-image.", Required: false),
    ];

    public static IEnumerable<ModelFile> RequiredFiles => Files.Where(file => file.Required);

    /// <summary>Checks a directory without loading anything.</summary>
    public static ModelDirectoryStatus Probe(string? directory)
    {
        if (string.IsNullOrWhiteSpace(directory))
        {
            return new ModelDirectoryStatus(
                directory ?? string.Empty,
                DirectoryExists: false,
                IsEmpty: true,
                Missing: RequiredFiles.ToArray(),
                Present: []);
        }

        if (!Directory.Exists(directory))
        {
            return new ModelDirectoryStatus(
                directory,
                DirectoryExists: false,
                IsEmpty: true,
                Missing: RequiredFiles.ToArray(),
                Present: []);
        }

        var present = new List<ModelFile>();
        var missing = new List<ModelFile>();

        foreach (ModelFile file in Files)
        {
            string full = Path.Combine(directory, file.RelativePath.Replace('/', Path.DirectorySeparatorChar));
            if (File.Exists(full))
            {
                present.Add(file);
            }
            else if (file.Required)
            {
                missing.Add(file);
            }
        }

        bool isEmpty = !Directory.EnumerateFileSystemEntries(directory).Any();

        return new ModelDirectoryStatus(directory, DirectoryExists: true, isEmpty, missing, present);
    }
}

/// <summary>Result of inspecting a model directory.</summary>
public sealed record ModelDirectoryStatus(
    string Directory,
    bool DirectoryExists,
    bool IsEmpty,
    IReadOnlyList<ModelFile> Missing,
    IReadOnlyList<ModelFile> Present)
{
    /// <summary>True when every required file is in place.</summary>
    public bool IsComplete => DirectoryExists && Missing.Count == 0;

    /// <summary>
    /// True when the wizard should open: no directory chosen yet, nothing in it,
    /// or nothing recognisable found.
    /// </summary>
    public bool NeedsFirstRunWizard => !DirectoryExists || IsEmpty || Present.Count == 0;

    /// <summary>
    /// A message for someone who has never opened a terminal: says what is
    /// missing and where it goes, without jargon.
    /// </summary>
    public string ToUserMessage()
    {
        if (IsComplete)
        {
            return $"All model files found in {Directory}.";
        }

        if (!DirectoryExists)
        {
            return "No model folder has been chosen yet. Pick the folder that holds your " +
                   "Stable Diffusion model files, then this window will check it for you.";
        }

        if (IsEmpty)
        {
            return $"The folder {Directory} is empty. It needs the Stable Diffusion model " +
                   "files copied into it - see the list below for what goes where.";
        }

        var lines = new List<string>
        {
            $"Some model files are missing from {Directory}:",
            string.Empty,
        };

        foreach (ModelFile file in Missing)
        {
            lines.Add($"  {file.RelativePath}  -  {file.Description}");
        }

        lines.Add(string.Empty);
        lines.Add("Copy the missing files into that folder, keeping the sub-folder names " +
                  "exactly as shown, then press Check again.");

        return string.Join(Environment.NewLine, lines);
    }
}
