@echo off
rem One-stop build for DeckGrade (native Windows variant of build.sh).
rem
rem Usage: build.bat [all|frontend|package|env]   (default: all)
rem
rem   all      frontend build + distribution zip
rem   frontend pnpm install + rollup build (dist/index.js)
rem   package  out\DeckGrade-v^<version^>.zip (+ .sha256), verified against the tree
rem   env      print the detected toolchain
setlocal

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "SCRIPT_DIR=%ROOT%"

set "STEP=%~1"
if "%STEP%"=="" set "STEP=all"

call :node_check || goto :fail
pushd "%ROOT%" || goto :fail

if "%STEP%"=="all" (
  call :frontend || goto :fail
  call :package || goto :fail
  goto :done
)
if "%STEP%"=="frontend" (
  call :frontend
  goto :done2
)
if "%STEP%"=="package" (
  call :package
  goto :done2
)
if "%STEP%"=="env" (
  echo repo root: %ROOT%
  for /f "delims=" %%i in ('node --version 2^>nul') do echo node: %%i
  for /f "delims=" %%i in ('pnpm --version 2^>nul') do echo pnpm: %%i
  goto :done
)
echo usage: %~nx0 [all|frontend|package|env] 1>&2
goto :fail

:frontend
call :pnpm_check || exit /b 1
echo == pnpm install
call pnpm install || exit /b 1
echo == pnpm build
call pnpm run build || exit /b 1
dir "%ROOT%\dist" || exit /b 1
exit /b 0

:package
node "%SCRIPT_DIR%\make_zip.mjs"
exit /b 0

:node_check
where node >nul 2>nul
if errorlevel 1 (
  echo error: node not found on PATH
  exit /b 1
)
exit /b 0

:pnpm_check
where pnpm >nul 2>nul
if errorlevel 1 (
  echo error: pnpm not found on PATH
  exit /b 1
)
exit /b 0

:done2
if errorlevel 1 goto :fail
goto :done

:done
popd
exit /b 0

:fail
popd
exit /b 1
