"""Separate updater: wait for Buddy to exit, stage/backup code, restart."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile

ALLOWED_ROOT={'app.py','buddy','requirements.txt','update_helper.py','start_buddy.bat','start_buddy_silent.vbs','VERSION.txt'}

def safe_entries(z):
    files=[]
    for item in z.infolist():
        path=Path(item.filename.replace('\\','/'))
        if item.is_dir(): continue
        if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] not in ALLOWED_ROOT:
            raise ValueError('Unsafe or unexpected update path: '+item.filename)
        if item.external_attr >> 16 & 0o170000 == 0o120000:
            raise ValueError('Symlinks are not allowed in updates.')
        files.append((item,path))
    if not any(str(p)=='app.py' for _,p in files): raise ValueError('Missing app.py in update.')
    return files

def apply(root, archive):
    state=root/'.buddy_update'; state.mkdir(exist_ok=True)
    stage=state/'stage'; backup=state/'backup'
    shutil.rmtree(stage,ignore_errors=True); shutil.rmtree(backup,ignore_errors=True)
    stage.mkdir();backup.mkdir()
    with zipfile.ZipFile(archive) as z:
        entries=safe_entries(z)
        for info,path in entries:
            dest=stage/path;dest.parent.mkdir(parents=True,exist_ok=True)
            with z.open(info) as src,dest.open('wb') as out: shutil.copyfileobj(src,out)
    # Keep .env, data, .venv, and all other user-owned files untouched.
    changed=[]
    try:
        for _,path in entries:
            destination=root/path
            if destination.exists():
                saved=backup/path;saved.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(destination,saved)
            changed.append(path)
            destination.parent.mkdir(parents=True,exist_ok=True)
            os.replace(stage/path,destination)
    except Exception:
        for path in reversed(changed):
            saved=backup/path; destination=root/path
            if saved.exists(): shutil.copy2(saved,destination)
            else: destination.unlink(missing_ok=True)
        raise
    return len(changed)

def install_dependencies(root, python=None):
    """Install the UPDATED requirements in the SAME environment used by Buddy.

    A code-only update may introduce packages not present in the older install.
    The updater must prepare those packages before declaring the update complete.
    """
    interpreter = python or sys.executable
    if sys.platform == 'win32':
        exe = Path(interpreter)
        # pythonw shares site-packages with python.exe but is unsuitable for
        # diagnostics; use its console sibling when available.
        if exe.name.lower() == 'pythonw.exe' and exe.with_name('python.exe').is_file():
            interpreter = str(exe.with_name('python.exe'))
    command = [str(interpreter), '-m', 'pip', 'install', '-r', str(root/'requirements.txt')]
    result = subprocess.run(command,cwd=root,capture_output=True,text=True,
                            timeout=300,check=False)
    if result.returncode:
        detail = (result.stderr or result.stdout or 'No diagnostic output').strip()
        raise RuntimeError('Python dependency install failed: '+detail[-1200:])
    return result.stdout


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',required=True);parser.add_argument('--archive',required=True)
    parser.add_argument('--pid',type=int,required=True)
    args=parser.parse_args();root=Path(args.root).resolve()
    log=root/'buddy-update.log'
    try:
        # Wait until the parent Buddy process is fully gone (Windows pid check).
        for _ in range(100):
            if sys.platform=='win32':
                import ctypes
                SYNCHRONIZE=0x00100000
                handle=ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE,False,args.pid)
                if not handle: break
                result=ctypes.windll.kernel32.WaitForSingleObject(handle,100)
                ctypes.windll.kernel32.CloseHandle(handle)
                if result==0: break
            else:
                try: os.kill(args.pid,0)
                except ProcessLookupError: break
            time.sleep(.2)
        else: raise RuntimeError('Buddy did not exit; update cancelled.')
        count=apply(root,Path(args.archive))
        # Match the Python runtime that will run Buddy; do not just replace code.
        install_dependencies(root)
        # The next launch alone may celebrate 100% after installation succeeded.
        version=(root/'VERSION.txt').read_text(encoding='utf8').strip()
        (root/'.buddy_update'/'completed_version.txt').write_text(version,encoding='utf8')
        log.write_text(f'Updated {count} application files successfully.\n',encoding='utf8')
    except Exception as exc:
        log.write_text(f'Update failed: {exc}\n',encoding='utf8')
    # Relaunch even after failed update, so Buddy remains accessible.
    python=sys.executable
    subprocess.Popen([python,str(root/'app.py')],cwd=root,
                     creationflags=getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0))

if __name__=='__main__': main()
