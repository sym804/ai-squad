Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
' Use this script's own folder as the working directory (no hardcoded install path).
WshShell.CurrentDirectory = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.Run "cmd /c set PYTHONIOENCODING=utf-8 && C:\Python311\python.exe -u watchdog.py", 0, False
