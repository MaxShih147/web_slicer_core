# M1 close run `m1-close-20260717T031801Z`

- scanner exit: **1** (FAIL)
- stripped nm global brand: **172**
- stripped nm local brand: **172**
- codesign Identifier: `slicer-engine`

## .ips
### overflow.ips
- procName=`slicer-engine` codeSigningID=`slicer-engine`
- Slic3r::=16 slic3r_main=0 prusaslicer=0
- threads=['slicer-engine', 'slicer-worker', 'slicer-engine', 'slicer-worker']

### segfault.ips
- procName=`slicer-engine` codeSigningID=`slicer-engine`
- Slic3r::=9 slic3r_main=0 prusaslicer=0
- threads=['slicer-engine', 'slicer-worker', 'slicer-engine', 'slicer-worker']

### exception.ips
- procName=`slicer-engine` codeSigningID=`slicer-engine`
- Slic3r::=8 slic3r_main=0 prusaslicer=0
- threads=['slicer-engine', 'slicer-worker', 'slicer-engine', 'slicer-worker']

## Notes / FAIL reasons
- overflow.ips: readable Slic3r:: stack symbols remain (16)
- segfault.ips: readable Slic3r:: stack symbols remain (9)
- exception.ips: readable Slic3r:: stack symbols remain (8)
