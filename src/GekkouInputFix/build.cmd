@echo off
rem Build GekkouInputFix.exe into dist\. Needs only the .NET Framework 4.x
rem compiler that ships with Windows 10/11.
setlocal
set CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe
if not exist "%CSC%" set CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe
if not exist "%CSC%" (
  echo Could not find csc.exe - install .NET Framework 4.x
  exit /b 1
)
set OUT=%~dp0..\..\dist
if not exist "%OUT%" mkdir "%OUT%"
"%CSC%" -nologo -target:winexe -optimize+ -out:"%OUT%\GekkouInputFix.exe" "%~dp0main.cs"
if errorlevel 1 exit /b 1
echo Built: %OUT%\GekkouInputFix.exe
