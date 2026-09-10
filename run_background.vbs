' Double-click to start ScreenPulse watching in the background — no window.
' Logs to %LOCALAPPDATA%\ScreenPulse\watch.log. Stop it with stop_background.bat
' or:  python -m screenpulse stop
Dim sh, here
Set sh = CreateObject("WScript.Shell")
here = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = here
' 0 = hidden window, False = don't wait for it to finish
sh.Run """" & here & "\run_background.bat""", 0, False
