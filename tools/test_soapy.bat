@echo off
call C:\Users\jakel\radioconda\Scripts\activate.bat
set "PATH=C:\Users\jakel\radioconda\Library\bin;%PATH%"
set "SOAPY_SDR_PLUGIN_PATH=C:\Users\jakel\radioconda\Library\lib\SoapySDR\modules0.8"
C:\Users\jakel\radioconda\python.exe -c "import SoapySDR; print('API:', SoapySDR.getAPIVersion()); results = SoapySDR.Device.enumerate('driver=hackrf'); print('HackRF devices:', len(results)); [print(' ', r) for r in results]"
pause
