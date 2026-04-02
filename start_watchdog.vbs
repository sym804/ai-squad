Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\ymseo\Documents\slack-multi-agent"
WshShell.Run "cmd /c set PYTHONIOENCODING=utf-8 && C:\Python311\python.exe -u watchdog.py", 0, False
