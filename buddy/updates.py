"""GitHub Releases update discovery and verified staging. No third-party deps."""
import hashlib
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlparse
from .version import VERSION

class UpdateError(Exception): pass

def version_tuple(s):
    try: return tuple(int(x) for x in str(s).lstrip('v').split('.'))
    except ValueError: raise UpdateError('Invalid release version')

def release_api():
    repo = os.environ.get('BUDDY_GITHUB_REPO', '').strip().strip('/')
    if not repo or len(repo.split('/')) != 2:
        raise UpdateError('Set BUDDY_GITHUB_REPO=owner/repository in .env first.')
    return f'https://api.github.com/repos/{repo}/releases/latest'

def get_json(url):
    req=Request(url,headers={'User-Agent':'Buddy-Day-Zero-Updater','Accept':'application/vnd.github+json'})
    with urlopen(req,timeout=20) as response:
        return json.load(response)

def check_release():
    release=get_json(release_api())
    assets={a['name']:a for a in release.get('assets',[])}
    manifest_asset=assets.get('buddy-manifest.json')
    bundle_asset=assets.get('buddy-day-zero-update.zip')
    if not manifest_asset or not bundle_asset: raise UpdateError('Release is missing required update assets.')
    manifest=get_json(manifest_asset['browser_download_url'])
    version=manifest.get('version','')
    if version.lstrip('v') != release.get('tag_name','').lstrip('v'):
        raise UpdateError('Release and manifest versions do not match.')
    checksum=manifest.get('sha256','')
    if len(checksum)!=64 or any(c not in '0123456789abcdef' for c in checksum.lower()):
        raise UpdateError('Release manifest has an invalid checksum.')
    return {'version':version,'newer':version_tuple(version)>version_tuple(VERSION),
            'url':bundle_asset['browser_download_url'],'sha256':checksum.lower(),
            'notes':release.get('body','')[:1500]}

def download_verified(release, folder, progress=None):
    folder=Path(folder); folder.mkdir(parents=True,exist_ok=True)
    destination=folder/'buddy-day-zero-update.zip'
    temp=destination.with_suffix('.part')
    sha=hashlib.sha256()
    req=Request(release['url'],headers={'User-Agent':'Buddy-Day-Zero-Updater'})
    try:
        with urlopen(req,timeout=60) as response, temp.open('wb') as out:
            total=0
            expected=max(1, int(response.headers.get('Content-Length', 0) or 0))
            while True:
                chunk=response.read(1024*256)
                if not chunk: break
                total+=len(chunk)
                if total>60*1024*1024: raise UpdateError('Update exceeds the 60 MB safety limit.')
                sha.update(chunk);out.write(chunk)
                if progress is not None and expected > 1:
                    progress(min(88, int(5+83*total/expected)))
        if sha.hexdigest()!=release['sha256']:
            raise UpdateError('Update checksum mismatch. Nothing was installed.')
        os.replace(temp,destination)
        if progress is not None:
            progress(92)
        return destination
    finally:
        temp.unlink(missing_ok=True)
