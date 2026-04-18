"""
BBagio 공통 업로더 모듈
업로드 시도 순서:
  1차: GitHub Pages (HTTPS port 443) — 방화벽 완전 우회
  2차: SFTP port 22
  3차: SFTP port 2222
  4차: FTP Passive port 21
  5차: FTP Active  port 21
"""

import ftplib
from pathlib import Path


# ═══════════════════════════════════════════════════════════════
#  1차: GitHub Pages (HTTPS API, 절대 방화벽 안 막힘)
# ═══════════════════════════════════════════════════════════════
def upload_github_pages(local_path, filename, github_token, github_user, github_repo,
                        branch="gh-pages"):
    """
    GitHub Pages에 파일 업로드 (HTTPS port 443).
    - 최초: 파일 생성
    - 이후: SHA 조회 후 업데이트
    성공 시 public URL 반환, 실패 시 예외 발생.
    """
    import base64, requests as req

    local_path = Path(local_path)
    content_b64 = base64.b64encode(local_path.read_bytes()).decode()

    api_url = (
        f"https://api.github.com/repos/{github_user}/{github_repo}"
        f"/contents/{filename}"
    )
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # 기존 파일 SHA 조회 (update에 필요)
    sha = None
    try:
        r = req.get(api_url, headers=headers,
                    params={"ref": branch}, timeout=15)
        if r.status_code == 200:
            sha = r.json().get("sha")
    except Exception:
        pass

    payload = {
        "message": f"chore: update {filename}",
        "content": content_b64,
        "branch":  branch,
    }
    if sha:
        payload["sha"] = sha

    r = req.put(api_url, headers=headers, json=payload, timeout=60)
    if r.status_code in (200, 201):
        public_url = f"https://{github_user}.github.io/{github_repo}/{filename}"
        return public_url
    else:
        raise Exception(
            f"GitHub API {r.status_code}: {r.json().get('message', r.text[:200])}"
        )


def ensure_gh_pages_branch(github_token, github_user, github_repo):
    """
    gh-pages 브랜치가 없으면 빈 커밋으로 생성.
    최초 1회만 필요.
    """
    import requests as req

    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    base = f"https://api.github.com/repos/{github_user}/{github_repo}"

    # 브랜치 존재 확인
    r = req.get(f"{base}/branches/gh-pages", headers=headers, timeout=15)
    if r.status_code == 200:
        return  # 이미 있음

    # default 브랜치의 SHA 가져오기
    r = req.get(f"{base}", headers=headers, timeout=15)
    default_branch = r.json().get("default_branch", "main")
    r = req.get(f"{base}/git/refs/heads/{default_branch}", headers=headers, timeout=15)
    sha = r.json()["object"]["sha"]

    # gh-pages 브랜치 생성
    req.post(f"{base}/git/refs", headers=headers, json={
        "ref": "refs/heads/gh-pages", "sha": sha
    }, timeout=15)
    print("  ✅ gh-pages 브랜치 생성 완료")


# ═══════════════════════════════════════════════════════════════
#  2~3차: SFTP
# ═══════════════════════════════════════════════════════════════
def _try_sftp(host, port, user, password, local_path, remote_dir, remote_filename):
    """SFTP 업로드 시도. 성공하면 True, 실패하면 예외 발생."""
    import paramiko
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, port=port, username=user, password=password,
                timeout=15, banner_timeout=15, auth_timeout=15)
    sftp = ssh.open_sftp()

    # 원격 디렉토리 이동 (없으면 생성)
    parts = remote_dir.strip("/").split("/")
    cur = ""
    for p in parts:
        cur += "/" + p
        try: sftp.mkdir(cur)
        except: pass
    sftp.chdir(remote_dir)

    sftp.put(str(local_path), remote_filename)
    sftp.close()
    ssh.close()
    return True


# ═══════════════════════════════════════════════════════════════
#  메인 업로드 함수
# ═══════════════════════════════════════════════════════════════
def upload_dashboard(local_path, remote_filename,
                     host="", user="", password="",
                     remote_dir="/web/dashboard/",
                     port_sftp=22, port_ftp=21,
                     public_url="",
                     github_token="", github_user="", github_repo=""):
    """
    HTML 파일을 서버에 업로드합니다.
    1차: GitHub Pages (HTTPS 443)  ← 방화벽 우회
    2차: SFTP port 22
    3차: SFTP port 2222
    4차: FTP Passive port 21
    5차: FTP Active  port 21
    """
    local_path = Path(local_path)
    print(f"\n  📤 업로드 중: {remote_filename}")

    # ── 1차: GitHub Pages ────────────────────────────────────
    if github_token and github_user and github_repo:
        try:
            print(f"  🔗 GitHub Pages 시도 (HTTPS)...", end=" ", flush=True)
            ensure_gh_pages_branch(github_token, github_user, github_repo)
            url = upload_github_pages(
                local_path, remote_filename,
                github_token, github_user, github_repo
            )
            print(f"✅ 완료 → {url}")
            return url
        except Exception as e:
            print(f"실패: {e}")

    # ── 2~3차: SFTP (22, 2222) ───────────────────────────────
    if host and user and password:
        try:
            import paramiko
            for sftp_port in [port_sftp, 2222]:
                try:
                    print(f"  🔗 SFTP 시도 (port {sftp_port})...", end=" ", flush=True)
                    _try_sftp(host, sftp_port, user, password,
                              local_path, remote_dir, remote_filename)
                    url = (public_url.rstrip("/") + "/" + remote_filename) if public_url else ""
                    print(f"✅ 완료" + (f" → {url}" if url else ""))
                    return url or True
                except Exception as e:
                    print(f"실패: {e}")
        except ImportError:
            print("  ⚠ paramiko 미설치 → install.bat 실행 후 재시도 권장")

        # ── 4~5차: FTP (Passive / Active) ───────────────────
        for pasv in [True, False]:
            mode = "Passive" if pasv else "Active"
            try:
                print(f"  🔗 FTP({mode}) 시도...", end=" ", flush=True)
                ftp = ftplib.FTP(timeout=30)
                ftp.connect(host, port_ftp, timeout=30)
                ftp.login(user, password)
                ftp.set_pasv(pasv)

                dirs = [d for d in remote_dir.strip("/").split("/") if d]
                ftp.cwd("/")
                for d in dirs:
                    try: ftp.cwd(d)
                    except: ftp.mkd(d); ftp.cwd(d)

                with open(local_path, "rb") as f:
                    ftp.storbinary(f"STOR {remote_filename}", f)
                ftp.quit()

                url = (public_url.rstrip("/") + "/" + remote_filename) if public_url else ""
                print(f"✅ 완료" + (f" → {url}" if url else ""))
                return url or True

            except Exception as e:
                print(f"실패: {e}")

    # ── 전부 실패 ─────────────────────────────────────────────
    print()
    print("  ━━━ 업로드 실패 — 수동 안내 ━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  로컬 파일: {local_path}")
    if github_token:
        print("  GitHub Pages: github_token/user/repo 설정 확인 필요")
    if host:
        print("  카페24 관리자 → 호스팅 관리 → 웹 FTP →")
        print(f"  {remote_dir} 경로에 {remote_filename} 수동 업로드")
        if public_url:
            print(f"  업로드 후 URL: {public_url.rstrip('/')}/{remote_filename}")
    print("  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return None


# ═══════════════════════════════════════════════════════════════
#  GitHub Pages + FTP 동시 업로드 (둘 다 성공해야 완전 완료)
# ═══════════════════════════════════════════════════════════════
def upload_both(local_path, remote_filename,
                host="", user="", password="",
                remote_dir="/web/dashboard/",
                port_sftp=22, port_ftp=21,
                public_url="",
                github_token="", github_user="", github_repo=""):
    """
    GitHub Pages와 FTP 양쪽에 모두 업로드합니다.
    - GitHub Pages 실패해도 FTP 시도
    - FTP 실패해도 GitHub 성공이면 URL 반환
    """
    local_path = Path(local_path)
    print(f"\n  📤 듀얼 업로드 중: {remote_filename}")
    results = []

    # ── GitHub Pages ─────────────────────────────────────────
    if github_token and github_user and github_repo:
        try:
            print(f"  🔗 GitHub Pages...", end=" ", flush=True)
            ensure_gh_pages_branch(github_token, github_user, github_repo)
            gh_url = upload_github_pages(
                local_path, remote_filename,
                github_token, github_user, github_repo
            )
            print(f"✅ → {gh_url}")
            results.append(gh_url)
        except Exception as e:
            print(f"❌ 실패: {e}")

    # ── FTP (SFTP → Passive → Active) ────────────────────────
    if host and user and password:
        import socket
        ftp_ok = False

        # 포트 접속 가능 여부 사전 체크 (3초) — 막히면 전체 스킵
        def _port_open(h, p, t=3):
            try:
                socket.create_connection((h, p), timeout=t).close()
                return True
            except Exception:
                return False

        ftp_reachable = _port_open(host, 22) or _port_open(host, 21)
        if not ftp_reachable:
            print(f"  ⚡ FTP/SFTP 포트 차단 감지 → 스킵")
        else:
            # SFTP 시도
            try:
                import paramiko
                for sftp_port in [port_sftp, 2222]:
                    try:
                        print(f"  🔗 SFTP(port {sftp_port})...", end=" ", flush=True)
                        _try_sftp(host, sftp_port, user, password,
                                  local_path, remote_dir, remote_filename)
                        ftp_url = (public_url.rstrip("/") + "/" + remote_filename) if public_url else ""
                        print(f"✅" + (f" → {ftp_url}" if ftp_url else ""))
                        results.append(ftp_url or True)
                        ftp_ok = True
                        break
                    except Exception as e:
                        print(f"❌ 실패: {e}")
            except ImportError:
                pass

            # FTP Passive / Active
            if not ftp_ok:
                for pasv in [True, False]:
                    mode = "Passive" if pasv else "Active"
                    try:
                        print(f"  🔗 FTP({mode})...", end=" ", flush=True)
                        ftp = ftplib.FTP(timeout=10)
                        ftp.connect(host, port_ftp, timeout=10)
                        ftp.login(user, password)
                        ftp.set_pasv(pasv)
                        dirs = [d for d in remote_dir.strip("/").split("/") if d]
                        ftp.cwd("/")
                        for d in dirs:
                            try: ftp.cwd(d)
                            except: ftp.mkd(d); ftp.cwd(d)
                        with open(local_path, "rb") as f:
                            ftp.storbinary(f"STOR {remote_filename}", f)
                        ftp.quit()
                        ftp_url = (public_url.rstrip("/") + "/" + remote_filename) if public_url else ""
                        print(f"✅" + (f" → {ftp_url}" if ftp_url else ""))
                        results.append(ftp_url or True)
                        ftp_ok = True
                        break
                    except Exception as e:
                        print(f"❌ 실패: {e}")

            if not ftp_ok:
                print(f"  ⚠️  FTP 업로드 실패 — {remote_filename} 수동 업로드 필요")

    return results[0] if results else None
