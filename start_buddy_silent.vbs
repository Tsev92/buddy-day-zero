Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
' Match the "py" launcher used by start_buddy.bat, but with a windowless interpreter.
shell.Run "pyw app.py", 0, False
