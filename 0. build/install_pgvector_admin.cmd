@echo off
set "PGROOT=C:\Program Files\PostgreSQL\18"
set "SRC=C:\python\ARCHITON\build\pgvector-0.8.2"
copy /Y "%SRC%\vector.dll" "%PGROOT%\lib" || exit /b 1
copy /Y "%SRC%\vector.control" "%PGROOT%\share\extension" || exit /b 1
copy /Y "%SRC%\sql\vector--*.sql" "%PGROOT%\share\extension" || exit /b 1
if not exist "%PGROOT%\include\server\extension\vector" mkdir "%PGROOT%\include\server\extension\vector"
copy /Y "%SRC%\src\halfvec.h" "%PGROOT%\include\server\extension\vector" || exit /b 1
copy /Y "%SRC%\src\sparsevec.h" "%PGROOT%\include\server\extension\vector" || exit /b 1
copy /Y "%SRC%\src\vector.h" "%PGROOT%\include\server\extension\vector" || exit /b 1
exit /b 0
