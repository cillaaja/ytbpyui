#!/usr/bin/env python3
"""
Single-file app that combines:

* FastAPI backend (port 8000) to accept large file uploads directly to disk (streamed)
* Streamlit frontend (port 8501) for UI + controls, which uses a client-side uploader (bypasses Streamlit's file_uploader)
  Run:
  python app_single_file_streamlit_fastapi.py
  This will:
* start FastAPI (uvicorn) in a background thread on port 8000
* spawn a Streamlit process that re-executes this file with --streamlit flag and runs the Streamlit UI

Requirements (pip):
fastapi uvicorn[standard] aiofiles python-multipart streamlit

Notes:

* The Streamlit UI provides a pure-browser uploader (JS) that uploads directly to FastAPI (so upload does not flow through Streamlit server memory).
* Uploaded files are saved under ./uploads and appear in the Streamlit dropdown automatically.
* This is intended for localhost / trusted environment. If deploying public-facing, add auth and TLS.
  """

import os
import sys
import threading
import subprocess
import time
from pathlib import Path

# ---------- Common configuration ----------

UPLOAD_DIR = Path("./uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

FASTAPI_HOST = "0.0.0.0"
FASTAPI_PORT = 8000
STREAMLIT_PORT = 8501

# ---------- FastAPI app (backend for chunked/large uploads) ----------

def start_fastapi_app():
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import aiofiles

```
app = FastAPI(title="Large Upload Backend")

# Allow CORS for Streamlit frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/ping")
async def ping():
    return {"ok": True}

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    """
    Accepts a standard multipart/form-data upload with field name 'file'.
    Writes file to disk in streaming fashion using aiofiles.
    Returns simple JSON with filename and size.
    """
    # sanitize filename
    filename = os.path.basename(file.filename)
    if not filename:
        raise HTTPException(status_code=400, detail="Missing filename")
    dest_path = UPLOAD_DIR / filename

    # If file already exists, save with incremental suffix
    if dest_path.exists():
        base, ext = os.path.splitext(filename)
        counter = 1
        while True:
            candidate = UPLOAD_DIR / f"{base}({counter}){ext}"
            if not candidate.exists():
                dest_path = candidate
                break
            counter += 1

    total_written = 0
    CHUNK_SIZE = 1024 * 1024 * 4  # 4MB chunks

    try:
        async with aiofiles.open(dest_path, "wb") as out_file:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                await out_file.write(chunk)
                total_written += len(chunk)
    except Exception as e:
        # attempt to remove partially written file
        try:
            if dest_path.exists():
                dest_path.unlink()
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

    return JSONResponse({"filename": str(dest_path.name), "size_bytes": total_written})

import uvicorn
# Running uvicorn.run in this thread will block — but function is executed inside a thread.
uvicorn.run(app, host=FASTAPI_HOST, port=FASTAPI_PORT, log_level="info")
```

# ---------- Streamlit app (frontend) ----------

def run_streamlit_app():
import streamlit as st
import streamlit.components.v1 as components
import threading
import os
import time
import shutil

```
st.set_page_config(page_title="YouTube Live — Upload Besar", layout="wide")
st.title("YouTube Live — Upload Besar (Streamlit + FastAPI) 🎥")

st.markdown(
    """
    #### Cara kerja singkat
    - Backend FastAPI menerima upload **langsung** dari browser dan menulis ke disk per-chunk (bypass Streamlit memory).
    - Gunakan tombol di bawah untuk memilih file yang sudah diupload (folder `./uploads`) lalu mulai streaming menggunakan `ffmpeg`.
    - Jika ingin upload file besar: gunakan uploader browser (di bawah) — ia akan melakukan POST langsung ke FastAPI.
    """
)

col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("Uploader browser (bypass Streamlit)")
    st.markdown(
        """
        Pilih file (mp4, mkv, mov, flv, ...) lalu upload langsung ke backend FastAPI.
        Progress bar ditampilkan. Upload besar (GB) didukung karena file ditulis langsung ke disk oleh FastAPI.
        """
    )

    # HTML + JS uploader that posts directly to FastAPI/upload and shows progress
    uploader_html = f"""
    <div style="font-family: sans-serif;">
      <input id="fileInput" type="file" />
      <div style="margin-top:8px;">
        <button id="uploadBtn">Upload ke backend</button>
      </div>
      <div id="progressWrap" style="margin-top:8px; display:none;">
        <progress id="pbar" value="0" max="100" style="width:100%;"></progress>
        <div id="status" style="font-size:12px;margin-top:6px;"></div>
      </div>
      <script>
        const fileInput = document.getElementById('fileInput');
        const uploadBtn = document.getElementById('uploadBtn');
        const pbar = document.getElementById('pbar');
        const status = document.getElementById('status');
        const progressWrap = document.getElementById('progressWrap');

        uploadBtn.addEventListener('click', () => {{
          const f = fileInput.files[0];
          if (!f) {{
            alert('Pilih file dulu');
            return;
          }}
          const url = '{'http://localhost:' + str(FASTAPI_PORT) + '/upload'}';
          const form = new FormData();
          form.append('file', f, f.name);

          const xhr = new XMLHttpRequest();
          xhr.open('POST', url, true);

          xhr.upload.addEventListener('progress', (e) => {{
            if (e.lengthComputable) {{
              const pct = Math.round((e.loaded / e.total) * 100);
              pbar.value = pct;
              status.innerText = 'Uploading: ' + pct + '% — ' + (e.loaded / (1024*1024)).toFixed(2) + ' MB';
              progressWrap.style.display = 'block';
            }}
          }});
          xhr.onload = function() {{
            if (xhr.status === 200) {{
              status.innerText = 'Upload selesai: ' + xhr.responseText;
              // inform Streamlit by sending a message to parent (Streamlit can capture it)
              try {{
                const payload = {{event: 'upload_done', response: xhr.responseText}};
                window.parent.postMessage({{streamlitMessage: true, payload: payload}}, '*');
              }} catch (e) {{
                console.log('postMessage fail', e);
              }}
            }} else {{
              status.innerText = 'Upload gagal. Status: ' + xhr.status + ' ' + xhr.responseText;
            }}
          }};
          xhr.onerror = function() {{
            status.innerText = 'Upload error (network).';
          }};
          xhr.send(form);
        }});
      </script>
    </div>
    """

    # Render the uploader HTML. We will also capture messages via components. The return value will be None.
    components.html(uploader_html, height=160, scrolling=True)

    st.info("Catatan: Pastikan FastAPI backend berjalan di port 8000 (script ini menjalankannya otomatis).")

    st.subheader("File yang tersedia di server (./uploads)")
    files = sorted(os.listdir("uploads"))
    selected_file = st.selectbox("Pilih file untuk streaming", options=["-- pilih --"] + files)
    if selected_file and selected_file != "-- pilih --":
        st.write(f"✅ File siap: uploads/{selected_file}")
        video_path = os.path.abspath(os.path.join("uploads", selected_file))
    else:
        video_path = None

with col2:
    st.subheader("Kontrol Streaming (ffmpeg)")
    stream_key = st.text_input("Stream Key YouTube (dibutuhkan untuk mulai)")
    is_shorts = st.checkbox("Mode Shorts (720x1280)")

    st.markdown("Tombol Start/Stop menjalankan/perintah `ffmpeg` pada mesin yang menjalankan aplikasi ini.")

    start_btn = st.button("Mulai Streaming")
    stop_btn = st.button("Hentikan Streaming")

    log_box = st.empty()
    log_lines = []

    def append_log(s):
        log_lines.append(s)
        # show last 30 lines
        log_box.text("\n".join(log_lines[-30:]))

    # Simple ffmpeg runner in background
    if 'ffmpeg_proc' not in st.session_state:
        st.session_state.ffmpeg_proc = None

    if start_btn:
        if not video_path:
            st.error("Pilih file dulu dari dropdown 'File yang tersedia di server'.")
        elif not stream_key:
            st.error("Masukkan stream key YouTube.")
        else:
            # Build ffmpeg command
            scale_arg = ["-vf", "scale=720:1280"] if is_shorts else []
            output_url = f"rtmp://a.rtmp.youtube.com/live2/{stream_key}"
            cmd = [
                "ffmpeg", "-re", "-stream_loop", "-1", "-i", video_path,
                "-c:v", "libx264", "-preset", "veryfast", "-b:v", "2500k",
                "-maxrate", "2500k", "-bufsize", "5000k",
                "-g", "60", "-keyint_min", "60",
                "-c:a", "aac", "-b:a", "128k",
            ] + scale_arg + ["-f", "flv", output_url]

            append_log("Menjalankan: " + " ".join(cmd))
            try:
                # start ffmpeg as subprocess; stream stdout
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                st.session_state.ffmpeg_proc = proc

                # thread to read output
                def reader_thread(p):
                    try:
                        for ln in iter(p.stdout.readline, ""):
                            if not ln:
                                break
                            append_log(ln.strip())
                    except Exception as e:
                        append_log("ffmpeg reader error: " + str(e))
                t = threading.Thread(target=reader_thread, args=(proc,), daemon=True)
                t.start()
                st.success("Streaming dimulai — periksa log.")
            except Exception as e:
                append_log("Gagal menjalankan ffmpeg: " + str(e))
                st.error("Gagal menjalankan ffmpeg. Pastikan ffmpeg terinstal di PATH.")

    if stop_btn:
        proc = st.session_state.get("ffmpeg_proc")
        if proc:
            proc.kill()
            st.session_state.ffmpeg_proc = None
            st.warning("Streaming dihentikan (ffmpeg killed).")
            append_log("ffmpeg dihentikan oleh user.")
        else:
            st.info("Tidak ada proses ffmpeg berjalan.")

st.markdown("---")
st.markdown("**Catatan teknis & tips**")
st.markdown(
    """
    - Uploader mengirim file langsung ke FastAPI yang menulis file ke `./uploads` dalam chunk (4MB).
    - Jangan jalankan ini di server publik tanpa HTTPS dan otentikasi — tambahkan proteksi jika perlu.
    - Jika ingin resume/partial upload, kita bisa tambahkan chunked-resume logic (lebih kompleks).
    """
)
```

# ---------- Entrypoint logic ----------

def main():
# If launched with --streamlit, run only the streamlit UI (this process is started by the launcher).
if "--streamlit" in sys.argv:
# Run only Streamlit app function
run_streamlit_app()
return

```
# Otherwise, this is the launcher process: start FastAPI in a background thread and spawn Streamlit
print("Launcher: starting FastAPI backend thread...")
fastapi_thread = threading.Thread(target=start_fastapi_app, daemon=True)
fastapi_thread.start()

# Wait a moment for FastAPI to boot
time.sleep(1.2)

# Launch Streamlit in a separate process that re-invokes this file with --streamlit flag
print("Launcher: starting Streamlit process...")
# Build command: python -m streamlit run thisfile -- --streamlit
cmd = [sys.executable, "-m", "streamlit", "run", __file__, "--", "--streamlit", "--server.port", str(STREAMLIT_PORT)]
streamlit_proc = subprocess.Popen(cmd)
print(f"Streamlit launched (PID {streamlit_proc.pid}). Visit http://localhost:{STREAMLIT_PORT}")

try:
    # Keep launcher alive while child processes run
    while True:
        time.sleep(1.0)
        # if streamlit process ends, exit
        if streamlit_proc.poll() is not None:
            print("Streamlit process ended.")
            break
except KeyboardInterrupt:
    print("Interrupted — shutting down.")
finally:
    # attempt to terminate streamlit if still running
    try:
        streamlit_proc.terminate()
    except Exception:
        pass
    print("Launcher exiting.")
```

if **name** == "**main**":
main()
