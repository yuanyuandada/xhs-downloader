; 小红书下载器安装包脚本（Inno Setup 6）
; 免管理员权限：安装到当前用户目录，不弹 UAC
[Setup]
AppId={{8E5F2C7A-9B3D-4E6A-A1C4-7D2B5F8E9A01}
AppName=小红书下载器
AppVersion=1.1.2
AppPublisher=个人自用工具
DefaultDirName={userpf}\小红书下载器
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=.
OutputBaseFilename=小红书下载器安装包
SetupIconFile=..\icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=小红书下载器
UninstallDisplayIcon={app}\小红书下载器.exe

[Languages]
Name: "chinese"; MessagesFile: "compiler:Default.isl"

[Messages]
; ---- 把安装向导的关键界面换成中文（避免依赖外部语言包）----
SetupAppTitle=安装 - 小红书下载器
SetupWindowTitle=安装 - 小红书下载器
WelcomeLabel1=欢迎使用 小红书下载器 安装向导
WelcomeLabel2=这将在您的电脑上安装 小红书下载器。%n%n这是一个免费的个人自用工具：保存喜欢的小红书图文、视频和实况图，无水印。%n%n建议关闭其他程序后单击“下一步”继续。
SelectDirDesc=您想将 小红书下载器 安装在哪里？
SelectDirLabel3=安装向导将把 小红书下载器 安装到以下文件夹。
SelectDirBrowseLabel=若要继续，请单击“下一步”。想换文件夹请单击“浏览”。
ButtonBack=< 上一步(&B)
ButtonNext=下一步(&N) >
ButtonInstall=安装(&I)
ButtonFinish=完成(&F)
ButtonCancel=取消
ButtonBrowse=浏览(&R)...
ReadyLabel1=安装向导已准备好在您的电脑上安装 小红书下载器。
ReadyLabel2a=单击“安装”开始安装，或单击“上一步”更改设置。
InstallingLabel=正在安装 小红书下载器，请稍候…
FinishedHeadingLabel=小红书下载器 安装完成
FinishedLabelNoIcons=已成功将 小红书下载器 安装到您的电脑。%n%n桌面上会出现程序图标，双击即可使用。
FinishedLabel=已成功将 小红书下载器 安装到您的电脑。%n%n桌面上会出现程序图标，双击即可使用。
ExitSetupTitle=退出安装
ExitSetupMessage=安装尚未完成。现在退出吗？
ConfirmUninstall=您确定要完全移除 小红书下载器 及其所有组件吗？
UninstalledAll=小红书下载器 已成功地从您的电脑移除。

[Files]
Source: "..\dist\小红书下载器.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\使用说明.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userdesktop}\小红书下载器"; Filename: "{app}\小红书下载器.exe"
Name: "{userprograms}\小红书下载器"; Filename: "{app}\小红书下载器.exe"

[Run]
Filename: "{app}\小红书下载器.exe"; Description: "立即打开 小红书下载器"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 卸载时保留下载内容与数据（在 {app}\download 与 {app}\data），此处不删除
Type: files; Name: "{app}\使用说明.md"
