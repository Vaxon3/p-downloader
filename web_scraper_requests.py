import json
import os
import re
from urllib.parse import urljoin, urlparse
try:
    from curl_cffi import requests as crequests
    HAS_CURL_CFFI = True
except ImportError:
    import requests as crequests
    HAS_CURL_CFFI = False
from bs4 import BeautifulSoup

class RequestScraper:
    def __init__(self, config_path="config.json"):
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Config file not found: {config_path}")
        with open(config_path, "r") as f:
            self.config = json.load(f)
        
        if HAS_CURL_CFFI:
            self.session = crequests.Session(impersonate="chrome120")
        else:
            self.session = crequests.Session()
            
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.google.com/"
        }

    def search_website(self, site_name, query, page=1):
        site_cfg = self.config["websites"].get(site_name)
        if not site_cfg:
            print(f"Error: Site '{site_name}' not found.")
            return []
        
        if page > 1 and "search_url_pagination_template" in site_cfg:
            offset = (page - 1) * 50
            search_url = site_cfg["search_url_pagination_template"].format(query=crequests.utils.quote(query), page=page, offset=offset)
        else:
            search_url = site_cfg["search_url_template"].format(query=crequests.utils.quote(query))
            
        print(f"RequestScraper: Searching {site_name} (Page {page}) at {search_url}")
        try:
            resp = self.session.get(search_url, headers=self.headers, timeout=15)
            if resp.status_code != 200:
                print(f"Error: Status {resp.status_code}")
                return []
                
            soup = BeautifulSoup(resp.text, "html.parser")
            results = []
            items = soup.select(site_cfg["search_results_selector"])
            
            for item in items:
                try:
                    title_sel = site_cfg.get("result_title_selector")
                    link_sel = site_cfg.get("result_link_selector")
                    
                    title_tag = item.select_one(title_sel) if title_sel else item
                    link_tag = item.select_one(link_sel) if link_sel else item
                    
                    if not title_tag or not link_tag: continue
                    
                    title = ""
                    for attr in ["title", "aria-label", "data-jname", "oldtitle"]:
                        val = link_tag.get(attr) or title_tag.get(attr)
                        if val:
                            title = val.strip()
                            break
                    if not title:
                        title = title_tag.get_text(strip=True) or link_tag.get_text(strip=True)
                    
                    href = link_tag.get("href")
                    if title and href:
                        results.append({
                            "title": title,
                            "url": urljoin(site_cfg["base_url"], href),
                            "image_url": self._extract_image(item, site_cfg)
                        })
                except Exception as e:
                    print(f"Item extraction error: {e}")
                    continue
            print(f"Found {len(results)} results.")
            return results
        except Exception as e:
            print(f"Search failed: {e}")
            return []

    def get_episode_list(self, series_url, site_name, season_id=None):
        site_cfg = self.config["websites"].get(site_name)
        if not site_cfg: return []
        
        print(f"RequestScraper: Fetching episodes from {series_url}")
        try:
            resp = self.session.get(series_url, headers=self.headers, timeout=15)
            if resp.status_code != 200: return []
            
            soup = BeautifulSoup(resp.text, "html.parser")
            episodes = []
            
            container_sel = site_cfg.get("episode_list_container")
            item_sel = site_cfg.get("episode_item_selector")
            
            if not container_sel or not item_sel: return []
            
            container = soup.select_one(container_sel)
            if not container: return []
            
            items = container.select(item_sel)
            title_sel = site_cfg.get("episode_title_selector")
            link_sel = site_cfg.get("episode_link_selector")
            
            for item in items:
                try:
                    title_tag = item.select_one(title_sel) if title_sel else item
                    link_tag = item.select_one(link_sel) if link_sel else item
                    
                    title = title_tag.get_text(strip=True) or link_tag.get("title", "")
                    url = link_tag.get("href")
                    
                    if title and url:
                        episodes.append({
                            "title": title,
                            "url": urljoin(site_cfg["base_url"], url)
                        })
                except: continue
            return episodes
        except Exception as e:
            print(f"Episode fetch failed: {e}")
            return []

    def get_direct_video_link(self, video_page_url, site_name):
        site_cfg = self.config["websites"].get(site_name)
        if not site_cfg: return None
        
        print(f"RequestScraper: Extracting direct link from {video_page_url} ({site_name})")
        try:
            resp = self.session.get(video_page_url, headers=self.headers, timeout=15)
            if resp.status_code != 200: return None
            
            content = resp.text
            soup = BeautifulSoup(content, "html.parser")

            # 1. XVideos pattern
            if site_name == "xvideos":
                match = re.search(r'''setVideoUrlHigh\(['"]([^"']+)['"]\)''', content)
                if not match: match = re.search(r'''setVideoHLS\(['"]([^"']+)['"]\)''', content)
                if match: return {"url": match.group(1), "referer": video_page_url}

            # 2. Coomer pattern
            if site_name == "coomer":
                # Coomer links are often in a.fileThumb or post__attachment-link
                for link in soup.select("a.fileThumb, a.post__attachment-link"):
                    href = link.get("href")
                    if href and any(ext in href.lower() for ext in [".mp4", ".m3u8"]):
                        return {"url": urljoin(video_page_url, href), "referer": video_page_url}

            # 3. Erome pattern
            if site_name == "erome":
                # Erome often has multiple video/source tags
                video = soup.select_one("video source") or soup.select_one("video")
                if video and video.get("src"):
                    return {"url": urljoin(video_page_url, video["src"]), "referer": video_page_url}

            # Generic fallback: Look for common m3u8 or mp4 links in scripts
            stream_match = re.search(r'''https?://[^"']+\.(?:m3u8|mp4)[^"']*''', content)
            if stream_match:
                return {"url": stream_match.group(0), "referer": video_page_url}
            
            # Generic fallback: video/source tags
            video_tag = soup.find("video") or soup.find("source")
            if video_tag and video_tag.get("src"):
                return {"url": urljoin(video_page_url, video_tag["src"]), "referer": video_page_url}
                
            return None
        except Exception as e:
            print(f"Direct link extraction failed: {e}")
            return None

    def _extract_image(self, item, cfg):
        selector = cfg.get("result_image_selector")
        if not selector: return ""
        img = item.select_one(selector)
        if not img: return ""
        src = img.get("src") or img.get("data-src") or img.get("data-original")
        return urljoin(cfg["base_url"], src) if src else ""

if __name__ == "__main__":
    # Test script
    import sys
    scraper = RequestScraper()
    res = scraper.search_website("xvideos", "test")
    if res:
        print(f"First result: {res[0]['title']} - {res[0]['url']}")
        link = scraper.get_direct_video_link(res[0]['url'], "xvideos")
        print(f"Extracted Link: {link}")
