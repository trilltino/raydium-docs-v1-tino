#!/usr/bin/env python3
"""Deploy a commit of these docs to the review site on the Hetzner VPS.

The VPS serves the docs with `mint dev` in the `docs-preview` container, which mounts
/srv/docs-preview/site read-only and listens on 127.0.0.1:3012 behind nginx
(https://docs-review.178-104-55-19.sslip.io). This script follows the same method as the
XFChess website deploy: build locally, upload over SSH with the VPS key, fix permissions
on the server, then restart.

The nginx site (/etc/nginx/sites-available/docs-preview) also maps `<page>.md` to
`/_markdown/<page>`. `mint dev` serves Markdown only at the second path, and the
**Copy page** and **View as Markdown** buttons request the first. Keep that `location`
block if the server is rebuilt.

Steps:
1. `git archive` the site files of the chosen commit (default HEAD) into a tarball.
2. Upload it to /srv/docs-preview/releases/main-<sha>/ and unpack it into `staged/`.
3. Record the previous release, sync `staged/` into `site/` with rsync --delete, and make
   it world-readable.
4. Restart the container and wait until it answers on 127.0.0.1:3012.

Only committed files are deployed. Commit (and push) first.

Run:      py scripts/deploy-vps.py [--ref <commit>] [--dry-run]
Rollback: py scripts/deploy-vps.py --ref <older commit>

Override the defaults with DOCS_VPS_HOST (default root@178.104.55.19) and
DOCS_VPS_KEY (default ~/.ssh/xfchess_vps).
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOST = os.environ.get("DOCS_VPS_HOST", "root@178.104.55.19")
KEY = Path(os.environ.get("DOCS_VPS_KEY", Path.home() / ".ssh" / "xfchess_vps"))
BASE = "/srv/docs-preview"
CONTAINER = "docs-preview"
LOCAL_PORT = 3012
SITE_URL = "https://docs-review.178-104-55-19.sslip.io/"
# What the site needs; everything else in the repo (reports, research, prompts) stays local.
SITE_PATHS = [".mintignore", "docs", "docs.json", "favicon.ico", "images", "logo", "public", "scripts", "style.css"]
SSH_OPTS = ["-i", str(KEY), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=20"]


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def ssh(script, dry_run):
    print(f"$ ssh {HOST} <<'SH'\n{script}\nSH")
    if not dry_run:
        # Bytes, so Windows does not turn the newlines into CRLF, which the remote sh rejects.
        subprocess.run(["ssh", *SSH_OPTS, HOST, "sh -s"], input=script.replace("\r\n", "\n").encode(), check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref", default="HEAD", help="commit to deploy (default HEAD)")
    parser.add_argument("--dry-run", action="store_true", help="print the steps without uploading")
    args = parser.parse_args()

    if not KEY.exists():
        sys.exit(f"SSH key not found at {KEY}")
    sha = git("rev-parse", "--short", args.ref)
    release = f"main-{sha}"
    paths = [p for p in SITE_PATHS if git("ls-tree", "--name-only", args.ref, p)]
    if git("status", "--porcelain", "--", *paths) and args.ref == "HEAD":
        print("Note: uncommitted changes are not deployed; only the commit is.")
    print(f"Deploying {release}: {git('log', '-1', '--format=%s', args.ref)}")

    with tempfile.TemporaryDirectory() as tmp:
        tarball = Path(tmp) / f"{release}.tar.gz"
        git("archive", "--format=tar.gz", "-o", str(tarball), args.ref, *paths)
        print(f"Built {tarball.name} ({tarball.stat().st_size // 1024} KB)")

        remote_dir = f"{BASE}/releases/{release}"
        ssh(f"mkdir -p {remote_dir}", args.dry_run)
        print(f"$ scp {tarball.name} {HOST}:{remote_dir}/")
        if not args.dry_run:
            subprocess.run(["scp", *SSH_OPTS, str(tarball), f"{HOST}:{remote_dir}/"], check=True)

    ssh(f"""set -eu
cd {BASE}
rm -rf {remote_dir}/staged && mkdir -p {remote_dir}/staged
tar xzf {remote_dir}/{release}.tar.gz -C {remote_dir}/staged
test -f {remote_dir}/staged/docs.json
cat active-release > {remote_dir}/previous-active-release 2>/dev/null || true
rsync -a --delete {remote_dir}/staged/ site/
chmod -R a+rX site
echo {release} > active-release
docker restart {CONTAINER} >/dev/null
i=0
until code=$(curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{LOCAL_PORT}/) && [ "$code" != 000 ] && [ "$code" -lt 500 ]; do
  i=$((i + 1)); [ $i -ge 60 ] && echo "container did not answer after 5 minutes" && exit 1; sleep 5
done
echo "active release: $(cat active-release) (previous: $(cat {remote_dir}/previous-active-release 2>/dev/null))"
echo "127.0.0.1:{LOCAL_PORT} -> HTTP $code"
""", args.dry_run)

    print(f"Done. Site: {SITE_URL}")


if __name__ == "__main__":
    main()
