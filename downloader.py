import requests
import os
import time
import subprocess
import re
from urllib.parse import urljoin, urlparse
import yt_dlp 
from yt_dlp import YoutubeDL, DownloadError
from concurrent.futures import ThreadPoolExecutor, as_completed
import shutil # Added for rmtree

def download_with_yt_dlp_api(url, output_path, filename, progress_callback, referer, user_agent, cookie_file, convert_to_mp4=False, custom_headers=None):
    """
    Downloads using the yt-dlp Python API. This is the most reliable method for complex sites.
    """
    if progress_callback and progress_callback(0, 0, filename, check_cancel=True) == False:
        return "__CANCELLED__"

    print(f"Downloading {url} using yt-dlp API...")
    
    # Define the outtmpl for the file
    ext = 'mp4' if convert_to_mp4 else 'ts'
    outtmpl = os.path.join(output_path, f"{filename}.%(ext)s" if filename else f"%(title)s.%(ext)s")

    try:
        from yt_dlp.networking.impersonate import ImpersonateTarget
        impersonate_target = ImpersonateTarget('chrome')
    except ImportError:
        impersonate_target = 'chrome'

    # Build advanced headers similar to CLI version
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Upgrade-Insecure-Requests": "1",
    }
    
    if referer:
        headers["Referer"] = referer
        parsed_ref = urlparse(referer)
        origin = f"{parsed_ref.scheme}://{parsed_ref.netloc}"
        headers["Origin"] = origin
        
        # Dynamically set Sec-Fetch based on domains
        url_domain = urlparse(url).netloc
        ref_domain = parsed_ref.netloc
        headers["Sec-Fetch-Site"] = "same-origin" if url_domain == ref_domain else "cross-site"
        headers["Sec-Fetch-Mode"] = "cors"
        headers["Sec-Fetch-Dest"] = "empty" if any(x in url.lower() for x in [".m3u8", ".mp4", ".ts"]) else "video"

    if custom_headers:
        headers.update(custom_headers)

    ydl_opts = {
        'outtmpl': outtmpl,
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'impersonate': impersonate_target,
        'merge_output_format': 'mp4' if convert_to_mp4 else 'ts',
        'progress_hooks': [lambda d: _yt_dlp_progress_hook(d, progress_callback, filename)],
        'compatible_head': True,
        'retries': 15,
        'fragment_retries': 15,
        'concurrent_fragments': 15, # Lowered to avoid server strain
        'buffersize': 1024 * 1024, # 1MB buffer
        'http_chunk_size': 1024 * 1024, # 1MB chunks
        'http_headers': headers,
        'nokeepvideo': False, # Keep the video file if it's already there
    }

    if user_agent:
        ydl_opts['user_agent'] = user_agent.replace("HeadlessChrome", "Chrome").replace("Headless", "")
    if cookie_file:
        ydl_opts['cookiefile'] = cookie_file

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        # Check if any file was actually created (be flexible with extension)
        for f in os.listdir(output_path):
            if f.startswith(filename if filename else ""):
                if any(f.endswith(e) for e in ['mp4', 'ts', 'mkv', 'webm', 'part']):
                    fpath = os.path.join(output_path, f)
                    if os.path.getsize(fpath) > 1 * 1024 * 1024: # > 1 MB
                        if progress_callback:
                            progress_callback(100, 100, filename, status="Finished")
                        return fpath
        return None
    except DownloadError as de:
        if "Download cancelled" in str(de):
            # Check for partial file before returning
            for f in os.listdir(output_path):
                if f.startswith(filename if filename else "") and f.endswith(".part"):
                    return os.path.join(output_path, f)
            return "__CANCELLED__"
        print(f"yt-dlp API failed: {de}")
        return None
    except Exception as e:
        print(f"yt-dlp API unexpected error: {e}")
        return None

def download_file(url, output_path, filename=None, progress_callback=None, use_yt_dlp=True, referer=None, user_agent=None, cookie_file=None, convert_to_mp4=False, custom_headers=None):
    """
    Unified entry point for downloading. Prioritizes yt-dlp for maximum robustness.
    """
    if not os.path.exists(output_path):
        os.makedirs(output_path)

    # Sanitize filename
    if filename:
        filename = "".join([c for c in filename if c.isalnum() or c in (' ', '.', '_', '-')]).strip()

    # Pre-check: If file already exists and is large enough, don't re-download
    ext = 'mp4' if convert_to_mp4 else 'ts'
    final_path = os.path.join(output_path, f"{filename}.{ext}")
    if os.path.exists(final_path) and os.path.getsize(final_path) > 1 * 1024 * 1024: # > 1MB
        print(f"File already exists: {final_path}. Skipping download.")
        if progress_callback:
            progress_callback(100, 100, filename, status="Finished (Skipped)")
        return final_path

    # Step 1: Manual m3u8 downloader (highest priority for m3u8 links)
    if ".m3u8" in url.lower():
        print(f"Manual m3u8 downloader for: {url}")
        res = download_m3u8_manual(url, output_path, filename, progress_callback, referer, user_agent, cookie_file, convert_to_mp4, custom_headers=custom_headers)
        if res == "__CANCELLED__": return "__CANCELLED__"
        if res: return res

    # Post-m3u8 check: did it actually download but return None?
    if os.path.exists(final_path) and os.path.getsize(final_path) > 1 * 1024 * 1024:
        return final_path

    # Step 2: Use yt-dlp (API then CLI) - robust and fast
    if use_yt_dlp:
        print(f"Attempting download with yt-dlp: {url}")
        
        # 2.1 Try yt-dlp API (Best integration)
        res = download_with_yt_dlp_api(url, output_path, filename, progress_callback, referer, user_agent, cookie_file, convert_to_mp4, custom_headers=custom_headers)
        if res == "__CANCELLED__": return "__CANCELLED__"
        if res: return res
        
        # 2.2 Try yt-dlp CLI (Isolated process fallback)
        print("yt-dlp API failed, trying CLI...")
        res = download_with_yt_dlp_cli(url, output_path, filename, progress_callback, referer, user_agent, cookie_file, convert_to_mp4)
        if res == "__CANCELLED__": return "__CANCELLED__"
        if res: return res
        
        print("yt-dlp methods failed. Trying fallbacks...")

    # Post-yt-dlp check
    if os.path.exists(final_path) and os.path.getsize(final_path) > 1 * 1024 * 1024:
        return final_path

    # Final Step: Direct curl_cffi download
    print(f"Final attempt with direct curl_cffi: {url}")
    res = download_with_curl_cffi(url, output_path, filename, progress_callback, referer, user_agent, cookie_file)
    
    if res: return res
    if os.path.exists(final_path) and os.path.getsize(final_path) > 1 * 1024 * 1024:
        return final_path
    
    return None


def download_with_yt_dlp_cli(url, output_path, filename, progress_callback, referer, user_agent, cookie_file, convert_to_mp4=False):
    """
    Fallback to the actual yt-dlp command line tool.
    """
    import sys
    try:
        venv_yt_dlp_path = os.path.join(os.path.dirname(sys.executable), "yt-dlp")
        yt_dlp_path = venv_yt_dlp_path if os.path.exists(venv_yt_dlp_path) else "yt-dlp"

        # Sanitize filename
        clean_filename = "".join([c for c in filename if c.isalnum() or c in (' ', '.', '_', '-')]).strip()
        ext = 'mp4' if convert_to_mp4 else 'ts'
        output_file = os.path.join(output_path, f"{clean_filename}.%(ext)s")

        # Robust CLI command
        cmd = [
            yt_dlp_path,
            url,
            "-o", output_file,
            "--no-playlist",
            "--merge-output-format", ext,
            "--newline",
            "--no-warnings",
            "--no-check-certificate",
            "--geo-bypass",
            "--retries", "15",
            "--fragment-retries", "15",
            "--concurrent-fragments", "15",
            "--buffer-size", "1M",
            "--http-chunk-size", "1M",
            "--impersonate", "chrome"
        ]
        
        if referer: 
            cmd.extend(["--referer", referer])
            from urllib.parse import urlparse
            parsed_ref = urlparse(referer)
            origin = f"{parsed_ref.scheme}://{parsed_ref.netloc}"
            cmd.extend(["--add-header", f"Origin:{origin}"])
            cmd.extend(["--add-header", "Accept:text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"])
            cmd.extend(["--add-header", "Accept-Language:en-US,en;q=0.9"])
            cmd.extend(["--add-header", "Sec-Fetch-Mode:cors"])
            
            # Set Sec-Fetch-Dest based on URL extension/type
            if any(ext in url.lower() for ext in [".m3u8", ".mp4", ".ts", ".mkv", ".webm", ".mpd"]):
                cmd.extend(["--add-header", "Sec-Fetch-Dest:empty"])
            elif "embed" in url.lower() or ".html" in url.lower():
                cmd.extend(["--add-header", "Sec-Fetch-Dest:iframe"])
            else:
                cmd.extend(["--add-header", "Sec-Fetch-Dest:empty"])
            
            # Dynamically set Sec-Fetch-Site
            url_domain = urlparse(url).netloc
            ref_domain = urlparse(referer).netloc
            if url_domain == ref_domain:
                cmd.extend(["--add-header", "Sec-Fetch-Site:same-origin"])
            else:
                cmd.extend(["--add-header", "Sec-Fetch-Site:cross-site"])

            cmd.extend(["--add-header", 'Sec-Ch-Ua:"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"'])
            cmd.extend(["--add-header", "Sec-Ch-Ua-Mobile:?0"])
            cmd.extend(["--add-header", 'Sec-Ch-Ua-Platform:"Windows"'])
            cmd.extend(["--add-header", "Upgrade-Insecure-Requests:1"])
            
        if user_agent: 
            clean_ua = user_agent.replace("HeadlessChrome", "Chrome").replace("Headless", "")
            cmd.extend(["--user-agent", clean_ua])
            
        # Ensure we use the writable cookie path if in AppImage
        if not cookie_file and "APPDIR" in os.environ:
            alt_cookie = os.path.expanduser("~/.video_downloader_cookies.txt")
            if os.path.exists(alt_cookie):
                cookie_file = alt_cookie

        if cookie_file: cmd.extend(["--cookies", cookie_file])

        print(f"Executing CLI: {' '.join(cmd)}")
        
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        
        # Standard yt-dlp progress regex: [download]  12.3% of ...
        progress_re = re.compile(r"\[download\]\s+(\d+\.?\d*)%") 
        
        for line in process.stdout:
            match = progress_re.search(line)
            if match and progress_callback:
                try:
                    percent = float(match.group(1))
                    if progress_callback(percent, 100, filename, check_cancel=True) == False:
                        print("CLI download cancelled.")
                        process.terminate()
                        return "__CANCELLED__"
                except: pass
        
        process.wait()
        if progress_callback:
            if progress_callback(100, 100, clean_filename, check_cancel=True) == False:
                return "__CANCELLED__"
            progress_callback(100, 100, clean_filename, status="Post-processing...")
            
        if process.returncode == 0:
            # Check for ANY file with standard extensions starting with clean_filename
            for f in os.listdir(output_path):
                if f.startswith(clean_filename):
                    if any(f.endswith(e) for e in ['mp4', 'ts', 'mkv', 'webm']):
                        fpath = os.path.join(output_path, f)
                        if os.path.getsize(fpath) > 1 * 1024 * 1024: # > 1 MB
                            if progress_callback:
                                progress_callback(100, 100, clean_filename, status="Finished")
                            return fpath
        
        print(f"yt-dlp CLI failed with return code {process.returncode}.")
        return None

    except Exception as e:
        print(f"yt-dlp CLI execution failed: {e}")
        return None

def download_m3u8_manual(url, output_path, filename, progress_callback, referer, user_agent, cookie_file, convert_to_mp4=False, custom_headers=None):
    """
    Manual m3u8 downloader with retry logic for incomplete segment downloads or merge failures.
    """
    from curl_cffi import requests as cur_req
    import sys 
    import concurrent.futures

    final_ext = 'mp4' if convert_to_mp4 else 'ts'
    final_file = os.path.join(output_path, f"{filename}.{final_ext}")
    temp_dir = os.path.join(output_path, f".resume_{filename}")

    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)

    for attempt in range(3):
        print(f"M3U8 download attempt {attempt + 1}/3 for: {url}")
        try:
            headers = {
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "cross-site",
                "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
            }
            if referer: 
                headers["Referer"] = referer
                parsed_ref = urlparse(referer)
                headers["Origin"] = f"{parsed_ref.scheme}://{parsed_ref.netloc}"
                
                url_domain = urlparse(url).netloc
                ref_domain = parsed_ref.netloc
                if url_domain == ref_domain:
                    headers["Sec-Fetch-Site"] = "same-origin"
                else:
                    headers["Sec-Fetch-Site"] = "cross-site"
            
            if custom_headers:
                headers.update(custom_headers)
            
            if user_agent: 
                headers["User-Agent"] = user_agent.replace("HeadlessChrome", "Chrome").replace("Headless", "")
            else:
                headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            
            import http.cookiejar
            cookies = http.cookiejar.MozillaCookieJar(cookie_file)
            if cookie_file and os.path.exists(cookie_file):
                try:
                    cookies.load(ignore_discard=True, ignore_expires=True)
                except Exception as e:
                    print(f"Error loading cookies in download_m3u8_manual: {e}")
                    cookies = {}
            else:
                cookies = {}

            resp = None
            for _ in range(3): 
                try:
                    resp = cur_req.get(url, headers=headers, cookies=cookies, impersonate="chrome", timeout=20)
                    resp.raise_for_status()
                    break
                except Exception as e:
                    print(f"Playlist fetch failed (inner retry): {e}")
                    time.sleep(2)
            if resp is None:
                raise Exception("Failed to fetch M3U8 playlist after multiple retries.")
            
            playlist_url = url
            if "#EXT-X-STREAM-INF" in resp.text:
                lines = resp.text.splitlines()
                best_bandwidth = -1
                best_url = None
                for i, line in enumerate(lines):
                    if line.startswith("#EXT-X-STREAM-INF"):
                        bw_match = re.search(r"BANDWIDTH=(\d+)", line) # Fixed regex
                        if bw_match:
                            bw = int(bw_match.group(1))
                            if bw > best_bandwidth:
                                # Find next line that isn't a comment
                                for j in range(i + 1, len(lines)):
                                    if lines[j].strip() and not lines[j].startswith("#"):
                                        best_bandwidth = bw
                                        best_url = lines[j].strip()
                                        break
                if best_url:
                    playlist_url = urljoin(url, best_url)
                    print(f"Selected stream (BW: {best_bandwidth}): {playlist_url}")
                    resp = cur_req.get(playlist_url, headers=headers, cookies=cookies, impersonate="chrome", timeout=20)
                    resp.raise_for_status()

            segments = [urljoin(playlist_url, line.strip()) for line in resp.text.splitlines() if line.strip() and not line.startswith("#")]
            
            # If we still have very few segments but bandwidth was high, it might be a sub-playlist logic issue
            if len(segments) < 5 and "#EXT-X-STREAM-INF" not in resp.text:
                print(f"Very few segments ({len(segments)}) found. Checking if it's a nested playlist...")
                for line in resp.text.splitlines():
                    if line.strip() and not line.startswith("#") and ".m3u8" in line:
                        playlist_url = urljoin(playlist_url, line.strip())
                        print(f"Found nested playlist URL: {playlist_url}")
                        resp = cur_req.get(playlist_url, headers=headers, cookies=cookies, impersonate="chrome", timeout=20)
                        resp.raise_for_status()
                        segments = [urljoin(playlist_url, line.strip()) for line in resp.text.splitlines() if line.strip() and not line.startswith("#")]
                        break

            if not segments:
                print("No segments found in playlist.")
                continue

            total_segments = len(segments)
            completed_indices = set()
            for i in range(total_segments):
                seg_path = os.path.join(temp_dir, f"{i:05d}.ts")
                if os.path.exists(seg_path) and os.path.getsize(seg_path) > 0:
                    completed_indices.add(i)

            initial_completed_count = len(completed_indices)
            print(f"Attempt {attempt + 1}: Resuming from {initial_completed_count}/{total_segments} segments already downloaded.")
            
            def download_segment(session, index, seg_url):
                seg_path = os.path.join(temp_dir, f"{index:05d}.ts")
                if os.path.exists(seg_path) and os.path.getsize(seg_path) > 0:
                    return index, True
                
                for retry_seg in range(5):
                    try:
                        seg_resp = session.get(seg_url, headers=headers, impersonate="chrome", timeout=25)
                        seg_resp.raise_for_status()
                        if b"<!DOCTYPE html>" in seg_resp.content[:200] or b"<html" in seg_resp.content[:200].lower():
                            print(f"Segment {index} returned HTML instead of TS. Likely blocked.")
                            return index, False
                        with open(seg_path, "wb") as f:
                            f.write(seg_resp.content)
                        return index, True
                    except Exception as e:
                        if retry_seg == 4: 
                            # print(f"Segment {index} failed after 5 retries: {e}")
                            return index, False
                        time.sleep(1)
                return index, False

            current_downloaded_count = initial_completed_count
            with cur_req.Session() as session:
                if cookie_file and os.path.exists(cookie_file):
                    session.cookies.update(cookies)
                
                with ThreadPoolExecutor(max_workers=3) as executor:
                    pending_futures = {executor.submit(download_segment, session, i, segments[i]): i for i in range(total_segments) if i not in completed_indices}
                    
                    while pending_futures:
                        if progress_callback and progress_callback(0, 0, filename, check_cancel=True) == False:
                            executor.shutdown(wait=False, cancel_futures=True)
                            return "__CANCELLED__"
                        
                        done_futures, pending_futures = concurrent.futures.wait(pending_futures, timeout=1, return_when=concurrent.futures.FIRST_COMPLETED)
                        
                        for future in done_futures:
                            idx, success = future.result()
                            if success:
                                current_downloaded_count += 1
                                completed_indices.add(idx)
                            if progress_callback:
                                progress_callback(len(completed_indices), total_segments, filename)
                        
                        if done_futures:
                            time.sleep(3.0) # Small delay between batches to avoid 503s

            missing_count = total_segments - len(completed_indices)
            if missing_count > 3 and attempt < 2:
                print(f"Warning: {missing_count} segments missing after attempt {attempt + 1}. Retrying...")
                time.sleep(2)
                continue

            if missing_count > 0:
                print(f"Warning: Finishing with {missing_count} segments missing (Tolerance: 3).")

            list_file = os.path.join(temp_dir, "concat_list.txt")
            with open(list_file, "w") as f:
                for i in sorted(list(completed_indices)):
                    abs_path = os.path.abspath(os.path.join(temp_dir, f"{i:05d}.ts"))
                    f.write(f"file '{abs_path}'\n")

            merge_cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", final_file]
            try:
                subprocess.run(merge_cmd, check=True, capture_output=True)
                if os.path.exists(final_file) and os.path.getsize(final_file) > 100 * 1024:
                    with open(final_file, "rb") as f:
                        start_bytes = f.read(500).lower()
                        if b"<!doctype html>" in start_bytes or b"<html" in start_bytes:
                            if os.path.exists(final_file): os.remove(final_file)
                            return None
                    if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
                    return final_file
            except Exception:
                if os.path.exists(final_file) and os.path.getsize(final_file) > 100 * 1024:
                    with open(final_file, "rb") as f:
                        start_bytes = f.read(500).lower()
                        if b"<!doctype html>" in start_bytes or b"<html" in start_bytes:
                            if os.path.exists(final_file): os.remove(final_file)
                            return None
                    if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
                    return final_file
                if attempt < 2: time.sleep(5); continue
                return None
        except Exception:
            if attempt < 2: time.sleep(5); continue
            return None
    return None

def download_with_curl_cffi(url, output_path, filename, progress_callback, referer, user_agent, cookie_file):
    try:
        from curl_cffi import requests as cur_req
        headers = {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
            "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
        }
        if referer: 
            headers["Referer"] = referer
            parsed_ref = urlparse(referer)
            headers["Origin"] = f"{parsed_ref.scheme}://{parsed_ref.netloc}"
            url_domain = urlparse(url).netloc
            ref_domain = parsed_ref.netloc
            headers["Sec-Fetch-Site"] = "same-origin" if url_domain == ref_domain else "cross-site"
            headers["Sec-Fetch-Mode"] = "cors"
            headers["Sec-Fetch-Dest"] = "video"
        if user_agent: headers["User-Agent"] = user_agent.replace("HeadlessChrome", "Chrome").replace("Headless", "")
        
        import http.cookiejar
        cookies = http.cookiejar.MozillaCookieJar(cookie_file)
        if cookie_file and os.path.exists(cookie_file):
            try: cookies.load(ignore_discard=True, ignore_expires=True)
            except Exception: cookies = {}
        else: cookies = {}

        response = cur_req.get(url, stream=True, headers=headers, cookies=cookies, impersonate="chrome", timeout=20)
        response.raise_for_status()
        if "text/html" in response.headers.get("Content-Type", "").lower(): return None

        if not filename:
            filename = os.path.basename(url.split("?")[0]) or "downloaded_video"
        if not any(filename.endswith(ext) for ext in ['.mp4', '.ts', '.mkv', '.webm']): filename += ".mp4"

        full_path = os.path.join(output_path, filename)
        total_size = int(response.headers.get("content-length", 0))
        bytes_downloaded = 0
        with open(full_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    if progress_callback and progress_callback(0, 0, filename, check_cancel=True) == False:
                        f.close()
                        # Removed os.remove(full_path) to allow resume
                        return "__CANCELLED__"
                    f.write(chunk)
                    bytes_downloaded += len(chunk)
                    if progress_callback: progress_callback(bytes_downloaded, total_size, filename)

        if os.path.exists(full_path) and os.path.getsize(full_path) > 1 * 1024 * 1024: # > 1MB
            return full_path
        if os.path.exists(full_path): os.remove(full_path)
        return None
    except Exception: return None

def _yt_dlp_progress_hook(d, progress_callback, original_filename):
    if progress_callback is None: return
    current_filename = original_filename if original_filename else d.get('filename', 'downloading_file')
    if progress_callback(0, 0, current_filename, check_cancel=True) == False: raise DownloadError("Download cancelled by user")
    if d['status'] == 'downloading':
        total = d.get('total_bytes') or d.get('total_bytes_estimate')
        downloaded = d.get('downloaded_bytes', 0)
        if total: progress_callback(downloaded, total, current_filename)
        else: progress_callback(downloaded, downloaded * 2, current_filename) 
    elif d['status'] == 'finished': progress_callback(100, 100, current_filename)
