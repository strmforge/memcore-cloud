Option Explicit

Dim shell, fso, installRoot, toolsDir, powershellExe, guardianScript, commandLine, extraArguments, exitCode
Dim argumentIndex, argumentValue

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

toolsDir = fso.GetParentFolderName(WScript.ScriptFullName)
installRoot = fso.GetParentFolderName(toolsDir)
If WScript.Arguments.Count >= 1 Then
    installRoot = WScript.Arguments.Item(0)
End If
extraArguments = ""
For argumentIndex = 1 To WScript.Arguments.Count - 1
    argumentValue = LCase(WScript.Arguments.Item(argumentIndex))
    If argumentValue = "-skipcodexmcpguardtaskcheck" Then
        extraArguments = extraArguments & " -SkipCodexMcpGuardTaskCheck"
    ElseIf argumentValue = "-startupactivationonly" Then
        extraArguments = extraArguments & " -StartupActivationOnly"
    Else
        WScript.Quit 2
    End If
Next

powershellExe = shell.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\WindowsPowerShell\v1.0\powershell.exe"
guardianScript = fso.BuildPath(installRoot, "tools\windows_guardian.ps1")
commandLine = """" & powershellExe & """ -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & guardianScript & """ -InstallRoot """ & installRoot & """ -StartWatcher -Quiet" & extraArguments

exitCode = shell.Run(commandLine, 0, True)
WScript.Quit exitCode
