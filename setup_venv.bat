@echo off
echo Setting up Personal AI Assistant virtual environment...
python -m venv venv
echo Activating venv and installing dependencies...
call venv\Scripts\activate.bat
pip install --upgrade pip
pip install -r requirements.txt
echo.
echo Virtual environment setup complete!
echo To activate: venv\Scripts\activate.bat
echo To start: python start.py
pause
