# macOS 4.6 — signed DMG lifecycle sample PASS

**Date：** 2026-07-19  
**DMG：** `Bundle Launcher_mac_arm64_1.0.0-202607192111.dmg`  
**SHA256：** `D742769C2C4AEBBA1A9249304061575085EDDDC7EB6CC5EF1A1A275238E3B09E`  
**Mode：** user-space copy from DMG (install → scan → uninstall → reinstall → scan)

| Step | Result |
|------|--------|
| install_1 + --help (PrusaSlicer=0) + legal/ | **PASS** |
| scan_final after install | **PASS** |
| uninstall | **PASS** |
| reinstall + --help + scan_final | **PASS** |

Evidence folder: `/Users/sw-dev/repos/Bundle/web_slicer_core/openspec/changes/backend-slicer-engine-deidentification/evidence/macos/lifecycle-4.6-20260719T191245Z`
