[app]
title = Video Downloader
package.name = pdownloader
package.domain = org.vaxon
source.dir = .
source.include_exts = py,png,jpg,kv,json
source.include_patterns = assets/*,config.json
version = 1.0.0
requirements = python3, kivy, curl_cffi, beautifulsoup4, yt-dlp, requests, certifi, chardet, idna, urllib3, pillow

# Android specific
android.permissions = INTERNET, WRITE_EXTERNAL_STORAGE, READ_EXTERNAL_STORAGE
android.api = 33
android.minapi = 21
android.sdk = 33
android.ndk = 25b
android.archs = arm64-v8a, armeabi-v7a

# Pipelining binaries like ffmpeg
# On Android, yt-dlp often needs an internal ffmpeg or uses a specific library
# For prototype, we'll try to bundle it via android.add_libs or as a requirement
# but usually it's better to use an android-specific build of ffmpeg.
# requirements = python3, kivy, curl_cffi, beautifulsoup4, yt-dlp, ffmpeg-python

[buildozer]
log_level = 2
warn_on_root = 1
# (buildozer) bin_dir = ./bin
