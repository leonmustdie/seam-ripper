@echo off
rem Build SeamRipper.exe (one-folder distribution) with PyInstaller.
rem Run from the toolkit folder. Result: dist\SeamRipper\SeamRipper.exe
setlocal

py -m pip install --upgrade pyinstaller PySide6 pillow || goto :err
rem the native LZX decoder needs Visual Studio's C++ tools; without it the
rem build still works and reads containers with the slower Python decoder
py tools\lzxnative_src\build.py || echo Native LZX decoder not built, using the Python one.
py -m PyInstaller --noconfirm seamripper.spec || goto :err

echo.
echo Build done: dist\SeamRipper\SeamRipper.exe
echo Zip the dist\SeamRipper folder for release.
goto :eof

:err
echo Build failed.
exit /b 1
