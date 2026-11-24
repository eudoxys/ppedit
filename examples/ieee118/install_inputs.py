"""Install the PES GM 2027 reproduction inputs into a cvxopf clone

Usage: python3 examples/ieee118/install_inputs.py CLONE [SOURCE]

Places the ten input files listed in `SHA256SUMS` (paths relative to the
cvxopf clone root) into the clone, as step 1 of `README.md` does with
`unzip -n "$archive" 'experiments/*'`. Run it at that point, after
`git switch --detach 2edc6d3b...` and before `git status --porcelain`.

`9q9wtp_gen_and_load.csv` comes from this folder. The nine earlier study
records under `experiments/` are not kept in this repository (the largest
three are about 138 MB together); they are read from SOURCE:
`pes2027-reproduction-inputs.zip` or a directory holding the same
`experiments/` tree. Without SOURCE only the CSV is installed and the
missing records are listed.

Files already in the clone are not overwritten (like `unzip -n`); every
file is then checked against `SHA256SUMS`. Exits 1 if a file is missing
or a hash differs.
"""

import hashlib
import os
import shutil
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))

LOCAL = {
    "experiments/battery_terminal/data/9q9wtp_gen_and_load.csv": "9q9wtp_gen_and_load.csv",
}
"""Clone paths of the files kept in this folder, and their names here"""

def checksums() -> dict[str,str]:
    """Expected SHA-256 by clone-relative path, from `SHA256SUMS`"""
    result = {}
    with open(os.path.join(HERE,"SHA256SUMS"),encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                digest,path = line.split(maxsplit=1)
                result[path.strip()] = digest
    return result

def sha256(path:str) -> str:
    """SHA-256 of a file"""
    h = hashlib.sha256()
    with open(path,"rb") as fh:
        for block in iter(lambda:fh.read(1<<20),b""):
            h.update(block)
    return h.hexdigest()

def local_source(name:str) -> str|None:
    """Path of a file kept in this folder, or None"""
    path = os.path.join(HERE,LOCAL[name]) if name in LOCAL else None
    return path if path and os.path.isfile(path) else None

def install(clone:str,source:str|None=None) -> int:
    """Install the inputs into `clone`; return the exit status"""
    if not os.path.isdir(os.path.join(clone,".git")):
        print(f"not a git clone: {clone}",file=sys.stderr)
        return 1
    archive = zipfile.ZipFile(source) if source and os.path.isfile(source) else None
    members = set(archive.namelist()) if archive else set()
    status = 0
    for name,digest in checksums().items():
        target = os.path.join(clone,name)
        if os.path.exists(target):
            print(f"kept      {name}")
        else:
            os.makedirs(os.path.dirname(target),exist_ok=True)
            if (path := local_source(name)):
                shutil.copyfile(path,target)
                print(f"copied    {name}")
            elif archive and name in members:
                with archive.open(name) as src, open(target,"wb") as dst:
                    shutil.copyfileobj(src,dst)
                print(f"extracted {name}")
            elif source and os.path.isdir(source) and os.path.isfile(os.path.join(source,name)):
                shutil.copyfile(os.path.join(source,name),target)
                print(f"copied    {name} (from {source})")
            else:
                print(f"MISSING   {name}",file=sys.stderr)
                status = 1
                continue
        if sha256(target) != digest:
            print(f"BAD HASH  {name}",file=sys.stderr)
            status = 1
    return status

if __name__ == "__main__":
    if not 2 <= len(sys.argv) <= 3:
        print(__doc__.split("\n\n")[1],file=sys.stderr)
        sys.exit(2)
    sys.exit(install(*sys.argv[1:]))
