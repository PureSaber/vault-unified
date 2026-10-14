!macro NSIS_HOOK_PREUNINSTALL
  ; The update replaces the executable at the same path. Keep its registration.
  ${If} $UpdateMode <> 1
    ExecWait '"$INSTDIR\${MAINBINARYNAME}.exe" --unregister-browser-host' $0
    ${If} $0 != 0
      Abort "Could not remove the browser connection. Close the application and retry."
    ${EndIf}
  ${EndIf}
!macroend
