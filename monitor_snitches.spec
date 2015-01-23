# -*- mode: python -*-

import os
a = Analysis(['monitor_snitches.py'],
             pathex=['E:\\Ryan\\Documents\\GitHub\\snitch_alerts_moved'],
             hiddenimports=[],
             hookspath=None,
             runtime_hooks=None)
             
includes = []
for parent, directories, files in os.walk('static'):
    for file in files:
        path = os.path.join(parent, file)
        includes.append((path, path, 'DATA'))
a.datas += includes

print a.datas
             
pyz = PYZ(a.pure)
exe = EXE(pyz,
          a.scripts,
          a.binaries,
          a.zipfiles,
          a.datas,
          name='monitor_snitches.exe',
          debug=False,
          strip=None,
          upx=True,
          console=True )