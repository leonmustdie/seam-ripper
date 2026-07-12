@echo off
rem Build SeamRipper.exe (one-folder distribution) with PyInstaller.
rem Run from the toolkit folder. Result: dist\SeamRipper\SeamRipper.exe
setlocal

py -m pip install --upgrade pyinstaller PySide6 pillow || goto :err
py -m PyInstaller --noconfirm seamripper.spec || goto :err

echo.
echo Build done: dist\SeamRipper\SeamRipper.exe
echo Zip the dist\SeamRipper folder for release.
goto :eof

:err
echo Build failed.
exit /b 1
