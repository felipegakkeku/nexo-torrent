Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

rootDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
electronExe = rootDir & "\desktop\node_modules\electron\dist\electron.exe"
desktopDir = rootDir & "\desktop"

args = ""
If WScript.Arguments.Count > 0 Then
  args = " """ & WScript.Arguments(0) & """"
End If

cmd = """" & electronExe & """ """ & desktopDir & """" & args
objShell.Run cmd, 0, False
