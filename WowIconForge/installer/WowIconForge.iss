; Inno Setup 6 script for WoW Icon Forge.
;
; Build it through publish.ps1, which publishes first and passes the folder in:
;     .\publish.ps1 -Installer
;     .\publish.ps1 -ModelsDirectory C:\sd15-onnx -Installer
;
; Or compile directly, pointing at an existing publish folder:
;     iscc /DAppSourceDir=..\dist\app installer\WowIconForge.iss
;
; The models are several gigabytes and cannot live inside the executable. This
; script handles that both ways, and picks automatically:
;
;   * If the publish folder contains a "models" sub-folder, it is packaged and
;     installed alongside the app. The installer is large; first run is instant.
;   * If it does not, the installer stays small and the app's first-run wizard
;     downloads and verifies the models into the user's own AppData.
;
; Nothing else changes between the two: ModelDirectoryResolver looks beside the
; executable first and falls back to the per-user folder, so the same build
; works either way.

#ifndef AppSourceDir
  #define AppSourceDir "..\dist\app"
#endif

#define AppExeName "WowIconForge.exe"

; Read the version straight off the published binary so the installer and the
; app can never disagree about what this is.
#define AppVersion GetVersionNumbersString(AddBackslash(AppSourceDir) + AppExeName)
#if AppVersion == ""
  #define AppVersion "0.1.0.0"
#endif

; Detect bundled models at compile time.
#if FileExists(AddBackslash(AppSourceDir) + "models\unet\model.onnx")
  #define BundledModels
#endif

[Setup]
; Never change AppId: it is how Windows recognises an upgrade rather than a
; second parallel installation.
AppId={{7C4E6E2A-9E3B-4F51-9F2D-2A6B5C1D8E30}
AppName=WoW Icon Forge
AppVersion={#AppVersion}
AppVerName=WoW Icon Forge {#AppVersion}
AppPublisher=WowIconForge
DefaultDirName={autopf}\WoW Icon Forge
DefaultGroupName=WoW Icon Forge
UninstallDisplayIcon={app}\{#AppExeName}
OutputDir=..\dist
#ifdef BundledModels
OutputBaseFilename=WowIconForge-{#AppVersion}-with-models
#else
OutputBaseFilename=WowIconForge-{#AppVersion}-setup
#endif
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Self-contained win-x64 build: refuse anything that cannot run it.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.18362
; Admin for Program Files. The models are written to the user's own AppData by
; the app, so nothing needs elevation after install.
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
DisableProgramGroupPage=yes
LicenseFile=
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The published application. excludes keeps development leftovers out of the
; installer if someone points this at a bin folder by mistake.
Source: "{#AppSourceDir}\*"; DestDir: "{app}"; \
    Excludes: "*.pdb,*.xml,models\*"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

#ifdef BundledModels
; Bundled models. external/recursesubdirs would also work, but packaging them
; keeps the installer to a single file the user can copy to another machine.
Source: "{#AppSourceDir}\models\*"; DestDir: "{app}\models"; \
    Flags: ignoreversion recursesubdirs createallsubdirs
#endif

[Icons]
Name: "{group}\WoW Icon Forge"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,WoW Icon Forge}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\WoW Icon Forge"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,WoW Icon Forge}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Bundled models live under {app} and are removed with it. Downloaded models
; live in the user's AppData and are deliberately left alone - re-downloading
; several gigabytes because someone reinstalled would be a poor trade. The
; uninstaller offers to remove them below instead.
Type: filesandordirs; Name: "{app}\models"

[Code]
const
  ModelSubPath = '\WowIconForge\models';

function DownloadedModelsPath(): String;
begin
  Result := ExpandConstant('{localappdata}') + ModelSubPath;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Message: String;
begin
  if CurStep = ssPostInstall then
  begin
#ifdef BundledModels
    // Nothing to say: the models shipped with the installer and the app will
    // find them next to the executable.
#else
    if not DirExists(DownloadedModelsPath()) then
    begin
      Message :=
        'WoW Icon Forge is installed.' + #13#10#13#10 +
        'It still needs the Stable Diffusion model files, which are too large ' +
        'to include in the installer. The first time you run it, a setup ' +
        'window will offer to download them for you and check them as they ' +
        'arrive.' + #13#10#13#10 +
        'They will be saved to:' + #13#10 +
        DownloadedModelsPath() + #13#10#13#10 +
        'Make sure you have several gigabytes of free space. If you already ' +
        'have the model files, you can point the app at them instead and skip ' +
        'the download.';
      MsgBox(Message, mbInformation, MB_OK);
    end;
#endif
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Path: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Path := DownloadedModelsPath();
    if DirExists(Path) then
    begin
      if MsgBox('Also delete the downloaded model files?' + #13#10#13#10 + Path +
                #13#10#13#10 + 'Keep them if you plan to reinstall - they are ' +
                'several gigabytes and would have to be downloaded again.',
                mbConfirmation, MB_YESNO) = IDYES then
      begin
        DelTree(Path, True, True, True);
      end;
    end;
  end;
end;
