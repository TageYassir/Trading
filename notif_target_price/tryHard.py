import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
import subprocess
import threading
import os
import re
import shutil
import json

NO_WINDOW = 0x08000000 if os.name == 'nt' else 0


class TrailerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Trailer Downloader — JSON or URLs → MP4")
        self.root.geometry("820x780")
        self.is_downloading = False

        frame = ttk.Frame(root, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Parent folder:").grid(row=0, column=0, sticky=tk.W, pady=3)
        self.parent_var = tk.StringVar(value=os.path.expanduser("~"))
        ttk.Entry(frame, textvariable=self.parent_var, width=55).grid(row=0, column=1, sticky=tk.EW, padx=5)
        ttk.Button(frame, text="Browse...", command=self.browse_parent).grid(row=0, column=2)

        ttk.Label(frame, text="Save folder name:").grid(row=1, column=0, sticky=tk.W, pady=3)
        self.subfolder_var = tk.StringVar(value="trailers")
        ttk.Entry(frame, textvariable=self.subfolder_var, width=55).grid(row=1, column=1, sticky=tk.EW, padx=5)

        self.prefer_full_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame,
                        text="Prefer full video (videoUrl) over trailer when both exist",
                        variable=self.prefer_full_var).grid(row=2, column=1, sticky=tk.W, padx=5, pady=3)

        ttk.Label(frame, text="Input — paste JSON (whole API response) OR URLs one per line:").grid(
            row=3, column=0, columnspan=3, sticky=tk.W, pady=(12, 2))
        self.input_text = scrolledtext.ScrolledText(frame, height=10, wrap=tk.NONE)
        self.input_text.grid(row=4, column=0, columnspan=3, sticky=tk.NSEW, pady=5)

        btns = ttk.Frame(frame)
        btns.grid(row=5, column=0, columnspan=3, pady=8)
        self.extract_btn = ttk.Button(btns, text="Extract URLs →", command=self.extract_urls)
        self.extract_btn.pack(side=tk.LEFT, padx=5)
        self.download_btn = ttk.Button(btns, text="Start Download", command=self.start_download)
        self.download_btn.pack(side=tk.LEFT, padx=5)
        ttk.Button(btns, text="Check tools", command=self.check_tools).pack(side=tk.LEFT, padx=5)
        ttk.Button(btns, text="Clear all", command=self.clear_all).pack(side=tk.LEFT, padx=5)

        ttk.Label(frame, text="URL queue (edit before downloading):").grid(
            row=6, column=0, columnspan=3, sticky=tk.W)
        self.urls_text = scrolledtext.ScrolledText(frame, height=9, wrap=tk.NONE)
        self.urls_text.grid(row=7, column=0, columnspan=3, sticky=tk.NSEW, pady=5)

        ttk.Label(frame, text="Log:").grid(row=8, column=0, sticky=tk.W)
        self.log_text = scrolledtext.ScrolledText(frame, height=10, state=tk.DISABLED)
        self.log_text.grid(row=9, column=0, columnspan=3, sticky=tk.NSEW, pady=5)

        self.progress = ttk.Progressbar(frame, mode='determinate')
        self.progress.grid(row=10, column=0, columnspan=3, sticky=tk.EW, pady=5)

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(frame, textvariable=self.status_var).grid(row=11, column=0, columnspan=3, sticky=tk.W)

        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(4, weight=1)
        frame.rowconfigure(7, weight=1)
        frame.rowconfigure(9, weight=1)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------------------------------------------------------------- helpers

    def browse_parent(self):
        d = filedialog.askdirectory(initialdir=self.parent_var.get())
        if d:
            self.parent_var.set(d)

    def log(self, msg):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def clear_all(self):
        self.input_text.delete("1.0", tk.END)
        self.urls_text.delete("1.0", tk.END)
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state=tk.DISABLED)

    def check_tools(self):
        missing = [t for t in ("yt-dlp", "ffmpeg", "ffprobe") if shutil.which(t) is None]
        if missing:
            messagebox.showerror("Missing tools",
                                 f"Not found in PATH: {', '.join(missing)}\n\n"
                                 "Install:  winget install yt-dlp\n           winget install ffmpeg")
        else:
            messagebox.showinfo("OK", "yt-dlp, ffmpeg, ffprobe are on PATH.")

    # ---------------------------------------------------------------- extraction

    def extract_urls(self):
        text = self.input_text.get("1.0", tk.END).strip()
        if not text:
            messagebox.showwarning("Empty", "Paste JSON or URLs first.")
            return

        try:
            items = self._parse_input(text)
        except ValueError as e:
            messagebox.showerror("Parse error", str(e))
            return

        if not items:
            messagebox.showwarning("No URLs", "Nothing extracted.")
            return

        self.urls_text.delete("1.0", tk.END)
        for it in items:
            self.urls_text.insert(tk.END, it['url'] + "\n")

        self.log(f"Extracted {len(items)} URL(s).")
        # Summary of access types
        if items and any('access' in it for it in items):
            access_counts = {}
            for it in items:
                a = it.get('access') or '?'
                access_counts[a] = access_counts.get(a, 0) + 1
            summary = ", ".join(f"{k}={v}" for k, v in sorted(access_counts.items()))
            self.log(f"  access breakdown: {summary}")

    def _parse_input(self, text):
        text = text.strip()
        if text.startswith('{') or text.startswith('['):
            return self._parse_json(text)
        return self._parse_urls(text)

    def _parse_json(self, text):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}")

        videos = data.get('videos', []) if isinstance(data, dict) else data
        if not isinstance(videos, list):
            raise ValueError("JSON has no 'videos' list.")

        prefer_full = self.prefer_full_var.get()
        out = []
        seen = set()
        for v in videos:
            if not isinstance(v, dict):
                continue

            candidates = []
            if prefer_full:
                if v.get('videoUrl'):
                    candidates.append(v['videoUrl'])
                if v.get('trailerUrl'):
                    candidates.append(v['trailerUrl'])
            else:
                if v.get('trailerUrl'):
                    candidates.append(v['trailerUrl'])
                if v.get('videoUrl'):
                    candidates.append(v['videoUrl'])

            intro = v.get('introUrls')
            if isinstance(intro, dict):
                for res in ('1080p', '720p', '480p', '360p'):
                    if res in intro:
                        candidates.append(intro[res])
                        break

            url = next((u for u in candidates if u and u not in seen), None)
            if not url:
                continue
            seen.add(url)
            out.append({
                'url': url,
                'title': v.get('title', ''),
                'access': v.get('accessMode', ''),
                'duration': v.get('duration', 0),
            })
        return out

    def _parse_urls(self, text):
        out = []
        seen = set()
        for line in text.splitlines():
            line = line.strip().rstrip(',').strip().strip('"').strip("'").strip()
            if (line.startswith('http://') or line.startswith('https://')) and line not in seen:
                seen.add(line)
                out.append({'url': line})
        return out

    @staticmethod
    def extract_hash(url):
        m = re.search(r"/([0-9a-f]{32,})(?:/|$)", url)
        return m.group(1) if m else None

    # ---------------------------------------------------------------- download

    def start_download(self):
        if self.is_downloading:
            return

        raw = self.urls_text.get("1.0", tk.END)
        urls = [u.strip() for u in raw.splitlines()
                if u.strip().startswith(('http://', 'https://'))]
        if not urls:
            messagebox.showwarning("No URLs", "URL queue is empty. Click 'Extract URLs' first.")
            return

        parent = self.parent_var.get().strip()
        sub = self.subfolder_var.get().strip()
        if not parent or not os.path.isdir(parent):
            messagebox.showerror("Bad folder", "Parent folder does not exist.")
            return
        if not sub:
            messagebox.showerror("Bad folder", "Enter a save folder name.")
            return

        for tool in ("yt-dlp", "ffmpeg", "ffprobe"):
            if shutil.which(tool) is None:
                messagebox.showerror("Missing tool", f"{tool} not found on PATH.")
                return

        out_dir = os.path.join(parent, sub)
        raw_dir = os.path.join(out_dir, ".raw")
        os.makedirs(out_dir, exist_ok=True)
        os.makedirs(raw_dir, exist_ok=True)

        self.is_downloading = True
        self.download_btn.config(state=tk.DISABLED)
        self.extract_btn.config(state=tk.DISABLED)
        self.progress["maximum"] = len(urls)
        self.progress["value"] = 0
        self.log(f"=== Starting: {len(urls)} URL(s) → {out_dir} ===")

        threading.Thread(target=self.download_all,
                         args=(urls, out_dir, raw_dir),
                         daemon=True).start()

    def download_all(self, urls, out_dir, raw_dir):
        total = len(urls)
        success, skipped, failed = 0, 0, []

        for i, url in enumerate(urls, 1):
            try:
                h = self.extract_hash(url)
                if not h:
                    self.log(f"[{i}/{total}] SKIP (no hash in URL): {url[:80]}")
                    failed.append((url, "no hash in URL"))
                    continue

                out_file = os.path.join(out_dir, f"{h}.mp4")
                if os.path.exists(out_file) and os.path.getsize(out_file) > 1024:
                    self.log(f"[{i}/{total}] SKIP (already exists): {h}.mp4")
                    skipped += 1
                    continue

                self.log(f"[{i}/{total}] Downloading {h} ...")
                tmpl = os.path.join(raw_dir, f"{h}.%(ext)s")
                dl = subprocess.run(
                    ["yt-dlp", "--no-playlist", "--no-overwrites",
                     "--retries", "3", "--fragment-retries", "3",
                     "-o", tmpl, url],
                    capture_output=True, text=True,
                    encoding="utf-8", errors="replace",
                    creationflags=NO_WINDOW)

                if dl.returncode != 0:
                    err = (dl.stderr or dl.stdout or "").strip().splitlines()
                    msg = err[-1] if err else "unknown error"
                    self.log(f"  yt-dlp failed: {msg[:150]}")
                    failed.append((url, "yt-dlp error"))
                    continue

                raw_file = next(
                    (os.path.join(raw_dir, f) for f in os.listdir(raw_dir)
                     if f.startswith(h + ".")), None)
                if not raw_file or os.path.getsize(raw_file) < 1024:
                    self.log("  Downloaded file missing or empty")
                    failed.append((url, "empty download"))
                    continue

                self.log("  Processing ...")
                if not self._process_video(raw_file, out_file):
                    failed.append((url, "ffmpeg error"))
                    continue

                try:
                    os.remove(raw_file)
                except OSError:
                    pass

                size_mb = os.path.getsize(out_file) / (1024 * 1024)
                self.log(f"  Done: {h}.mp4 ({size_mb:.1f} MB)")
                success += 1

            except Exception as e:
                self.log(f"  ERROR: {e}")
                failed.append((url, str(e)))
            finally:
                self.root.after(0, self._update_progress, i, total)

        try:
            os.rmdir(raw_dir)
        except OSError:
            pass

        self.log("")
        self.log(f"=== Finished: {success} ok, {skipped} skipped, {len(failed)} failed ===")
        for url, reason in failed:
            self.log(f"  FAIL [{reason}]: {url[:120]}")

        self.root.after(0, self.finish)

    def _process_video(self, raw_file, out_file):
        # Check for HLS DVR timestamp bug by reading stream start_time
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=start_time", "-of", "csv=p=0", raw_file],
                capture_output=True, text=True, creationflags=NO_WINDOW)
            start_time = float(probe.stdout.strip() or 0)
        except (ValueError, AttributeError):
            start_time = 0.0

        if start_time > 1.0:
            self.log(f"  (DVR bug: start_time={start_time:.1f}s — compressing timeline)")
            cmd = ["ffmpeg", "-y", "-loglevel", "error",
                   "-i", raw_file,
                   "-vf", "setpts=N/FRAME_RATE/TB",
                   "-af", "asetpts=N/SR/TB",
                   "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                   "-c:a", "aac", "-b:a", "128k",
                   "-movflags", "+faststart",
                   out_file]
        else:
            self.log("  (normal timestamps — fast remux)")
            cmd = ["ffmpeg", "-y", "-loglevel", "error",
                   "-i", raw_file,
                   "-c", "copy",
                   "-movflags", "+faststart",
                   out_file]

        result = subprocess.run(cmd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace",
                                creationflags=NO_WINDOW)
        if result.returncode != 0:
            err = (result.stderr or "").strip().splitlines()
            self.log(f"  ffmpeg failed: {(err[-1] if err else 'unknown')[:150]}")
            return False
        return True

    def _update_progress(self, i, total):
        self.progress["value"] = i
        self.status_var.set(f"Progress: {i}/{total}")

    def finish(self):
        self.is_downloading = False
        self.download_btn.config(state=tk.NORMAL)
        self.extract_btn.config(state=tk.NORMAL)
        self.status_var.set("Done")

    def on_close(self):
        if self.is_downloading:
            if not messagebox.askyesno("Still downloading",
                                       "A download is in progress. Close anyway?"):
                return
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    TrailerApp(root)
    root.mainloop()