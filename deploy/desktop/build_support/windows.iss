#ifndef AppVersion
  #error Supply AppVersion
#endif
#ifndef WindowsVersion
  #error Supply WindowsVersion
#endif
#ifndef SourceDir
  #error Supply SourceDir
#endif
#ifndef IconFile
  #error Supply IconFile
#endif
#ifndef OutputDir
  #error Supply OutputDir
#endif
#ifndef ImageDir
  #error Supply ImageDir
#endif
#ifndef SizeMB
  #error Supply SizeMB
#endif

[Setup]
AppId={{8B79A062-067C-46D5-94D7-A27CBAA00C33}
AppName=Thimbleby
AppVersion={#AppVersion}
VersionInfoVersion={#WindowsVersion}.0
DefaultDirName={localappdata}\Programs\Thimbleby
DefaultGroupName=Thimbleby
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=Thimbleby-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\Thimbleby.exe
SetupIconFile={#IconFile}
CloseApplications=yes
RestartApplications=no
; Three pages say something: Welcome, a couple of choices (which ends in Install), and Installed. There is no licence
; page, no folder page, no Start-menu group page and no ready page.
WizardStyle=modern
; The modern style hides the Welcome page unless asked; the target's Welcome page carries the three facts.
DisableWelcomePage=no
WizardImageFile={#ImageDir}\side.bmp,{#ImageDir}\side@2x.bmp
WizardSmallImageFile={#ImageDir}\small.bmp,{#ImageDir}\small@2x.bmp
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
ShowLanguageDialog=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

; Every line the setup and the uninstaller say is here. The folder the work stays in is named as the person sees it.
[Messages]
WelcomeLabel1=Install Thimbleby
WelcomeLabel2=Your own assistant for the to-dos hiding in your mail and calendar. It runs on this computer and opens in its own window.%n%nFor you only. No administrator password.%n%nAbout a minute, and {#SizeMB} MB of space.%n%nYour work is kept in its own folder. Removing the app never deletes it.
WizardSelectTasks=A couple of choices
SelectTasksDesc=You can change both later.
SelectTasksLabel2=Starting when you sign in is off until you turn it on: Thimbleby then waits quietly in the tray until you open it. It's always in the Start menu too.
WizardInstalling=Installing
InstallingLabel=Installing Thimbleby...
FinishedHeadingLabel=Thimbleby is installed
FinishedLabel=It's in your Start menu. Setup continues in Thimbleby's window and takes about 15 minutes. You can stop and come back.
FinishedLabelNoIcons=It's in your Start menu. Setup continues in Thimbleby's window and takes about 15 minutes. You can stop and come back.
ConfirmUninstall=Remove Thimbleby from this computer?%n%nYour work stays in AppData\Local\Thimbleby: your workspace, backups and saved keys. Installing again picks it up.%n%nTo delete your work too, open Thimbleby first and use Settings > Advanced > Delete this workspace.
UninstalledAll=Thimbleby was removed from this computer. Your work is still in AppData\Local\Thimbleby.
UninstalledMost=Thimbleby was removed from this computer. Your work is still in AppData\Local\Thimbleby.
ButtonInstall=Install
ButtonFinish=Finish

[CustomMessages]
english.TaskDesktop=Put Thimbleby on the desktop
english.TaskSignIn=Start Thimbleby when I sign in to Windows
english.InstallsTo=Installs to %1
english.RunNow=Open Thimbleby now

[Tasks]
Name: "desktopicon"; Description: "{cm:TaskDesktop}"; Flags: checkedonce
Name: "signin"; Description: "{cm:TaskSignIn}"; Flags: unchecked

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Thimbleby"; Filename: "{app}\Thimbleby.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Thimbleby"; Filename: "{app}\Thimbleby.exe"; Tasks: desktopicon; WorkingDir: "{app}"

; The same run key and value the app's own "Start when I sign in" writes (engine/login_item.py), with the same quoting,
; so the two never disagree.
[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Thimbleby"; ValueData: """{app}\Thimbleby.exe"" ""--at-login"""; Tasks: signin; Flags: uninsdeletevalue

[Run]
Filename: "{app}\Thimbleby.exe"; Description: "{cm:RunNow}"; Flags: nowait postinstall skipifsilent

[Code]
procedure InitializeWizard;
var
  Note: TNewStaticText;
begin
  { The folder, as a line of text and no picker, under the two choices. }
  WizardForm.TasksList.Height := WizardForm.TasksList.Height - ScaleY(32);
  Note := TNewStaticText.Create(WizardForm);
  Note.Parent := WizardForm.SelectTasksPage;
  Note.AutoSize := False;
  Note.WordWrap := True;
  Note.Left := WizardForm.TasksList.Left;
  Note.Width := WizardForm.TasksList.Width;
  Note.Top := WizardForm.TasksList.Top + WizardForm.TasksList.Height + ScaleY(8);
  Note.Height := ScaleY(24);
  Note.Caption := FmtMessage(CustomMessage('InstallsTo'), [WizardDirValue]);
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  { With no ready page, the choices page is the last before the files are copied: its button says Install. }
  if CurPageID = wpSelectTasks then
    WizardForm.NextButton.Caption := SetupMessage(msgButtonInstall);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  { Whichever way "start at sign-in" was turned on, removing the app leaves no entry that points at nothing. }
  if CurUninstallStep = usPostUninstall then
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'Thimbleby');
end;
