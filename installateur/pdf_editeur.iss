; Programme d'installation de PDF Éditeur (Inno Setup 6)
; Construit par installateur\construire.ps1 : ne pas compiler à la main sans avoir construit
; le dossier dist\PDF Editeur avec PyInstaller.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{8E3A9F2C-6B1D-4C5E-9A7F-2D4B6C8E0F13}
AppName=PDF Éditeur
AppVersion={#AppVersion}
AppVerName=PDF Éditeur {#AppVersion}
AppPublisher=PDF Éditeur
DefaultDirName={autopf}\PDF Editeur
DefaultGroupName=PDF Éditeur
DisableProgramGroupPage=yes
; installation pour l'utilisateur, sans droits administrateur (au choix : pour tous)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=PDF-Editeur-Installation-{#AppVersion}
SetupIconFile=pdf_editeur.ico
UninstallDisplayIcon={app}\PDF Editeur.exe
UninstallDisplayName=PDF Éditeur
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes
CloseApplications=yes

[Languages]
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "bureau"; Description: "Créer une icône sur le Bureau"; GroupDescription: "Icônes :"
Name: "ouvriravec"; Description: "Proposer PDF Éditeur dans « Ouvrir avec » (PDF et Word)"; GroupDescription: "Fichiers :"

[Files]
Source: "..\dist\PDF Editeur\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\PDF Éditeur"; Filename: "{app}\PDF Editeur.exe"; Comment: "Lire, modifier et enregistrer des PDF"
Name: "{autoprograms}\PDF Éditeur (navigateur)"; Filename: "{app}\PDF Editeur.exe"; Parameters: "--web"; Comment: "L'éditeur dans le navigateur"
Name: "{autoprograms}\PDF Éditeur sur le téléphone"; Filename: "{app}\PDF Editeur.exe"; Parameters: "--web --reseau"; Comment: "Utiliser l'éditeur depuis un téléphone ou une tablette (même Wi-Fi)"
Name: "{autodesktop}\PDF Éditeur"; Filename: "{app}\PDF Editeur.exe"; Tasks: bureau

[Registry]
; type de document « PDFEditeur.Document » proposé dans « Ouvrir avec »
Root: HKA; Subkey: "Software\Classes\PDFEditeur.Document"; ValueType: string; ValueName: ""; ValueData: "Document (PDF Éditeur)"; Flags: uninsdeletekey; Tasks: ouvriravec
Root: HKA; Subkey: "Software\Classes\PDFEditeur.Document\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\PDF Editeur.exe,0"; Tasks: ouvriravec
Root: HKA; Subkey: "Software\Classes\PDFEditeur.Document\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\PDF Editeur.exe"" ""%1"""; Tasks: ouvriravec
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "PDFEditeur.Document"; ValueData: ""; Flags: uninsdeletevalue; Tasks: ouvriravec
Root: HKA; Subkey: "Software\Classes\.docx\OpenWithProgids"; ValueType: string; ValueName: "PDFEditeur.Document"; ValueData: ""; Flags: uninsdeletevalue; Tasks: ouvriravec
Root: HKA; Subkey: "Software\Classes\Applications\PDF Editeur.exe\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""; Flags: uninsdeletekey; Tasks: ouvriravec
Root: HKA; Subkey: "Software\Classes\Applications\PDF Editeur.exe\SupportedTypes"; ValueType: string; ValueName: ".docx"; ValueData: ""; Tasks: ouvriravec
Root: HKA; Subkey: "Software\Classes\Applications\PDF Editeur.exe\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\PDF Editeur.exe"" ""%1"""; Tasks: ouvriravec

[Run]
Filename: "{app}\PDF Editeur.exe"; Description: "Lancer PDF Éditeur maintenant"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
